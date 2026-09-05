from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import Engine, insert, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from incident_intel.approvals import (
    ApprovalDecisionRecord,
    Decision,
    DraftNotFound,
    DraftRecord,
    DraftStateConflict,
)
from incident_intel.auth import OperatorClaims
from incident_intel.db import approval_decisions, response_drafts
from incident_intel.ingestion import StorageUnavailable


@dataclass(frozen=True)
class PostgresApprovalRepository:
    engine: Engine

    def create_draft(
        self,
        incident_id: UUID,
        *,
        content: str,
        created_by: str,
    ) -> DraftRecord:
        draft_id = uuid4()
        try:
            with self.engine.begin() as connection:
                row = connection.execute(
                    insert(response_drafts)
                    .values(
                        id=draft_id,
                        incident_id=incident_id,
                        content=content,
                        created_by=created_by,
                    )
                    .returning(response_drafts)
                ).mappings().one()
        except SQLAlchemyError:
            raise StorageUnavailable from None
        return self._draft_from_row(row, None)

    def get_draft(self, draft_id: UUID) -> DraftRecord | None:
        try:
            with self.engine.connect() as connection:
                row = connection.execute(
                    select(
                        response_drafts,
                        *(
                            column.label(f"decision_{column.name}")
                            for column in approval_decisions.c
                        ),
                    )
                    .select_from(
                        response_drafts.outerjoin(
                            approval_decisions,
                            approval_decisions.c.draft_id == response_drafts.c.id,
                        )
                    )
                    .where(response_drafts.c.id == draft_id)
                ).mappings().one_or_none()
                if row is None:
                    return None
                decision = (
                    {
                        column.name: row[f"decision_{column.name}"]
                        for column in approval_decisions.c
                    }
                    if row["decision_id"] is not None
                    else None
                )
        except SQLAlchemyError:
            raise StorageUnavailable from None
        return self._draft_from_row(row, decision)

    def decide(
        self,
        draft_id: UUID,
        *,
        decision: Decision,
        operator: OperatorClaims,
        reason: str | None,
    ) -> DraftRecord:
        decision_id = uuid4()
        try:
            with self.engine.begin() as connection:
                current = connection.execute(
                    select(response_drafts)
                    .where(response_drafts.c.id == draft_id)
                    .with_for_update()
                ).mappings().one_or_none()
                if current is None:
                    raise DraftNotFound
                if current["status"] != "pending_review":
                    raise DraftStateConflict
                decision_row = connection.execute(
                    insert(approval_decisions)
                    .values(
                        id=decision_id,
                        draft_id=draft_id,
                        decision=decision,
                        operator_id=operator.operator_id,
                        operator_role=operator.role,
                        reason=reason,
                    )
                    .returning(approval_decisions)
                ).mappings().one()
                draft_row = connection.execute(
                    update(response_drafts)
                    .where(response_drafts.c.id == draft_id)
                    .values(status=decision, updated_at=decision_row["created_at"])
                    .returning(response_drafts)
                ).mappings().one()
        except (DraftNotFound, DraftStateConflict):
            raise
        except IntegrityError:
            raise DraftStateConflict from None
        except SQLAlchemyError:
            raise StorageUnavailable from None
        return self._draft_from_row(draft_row, decision_row)

    @staticmethod
    def _draft_from_row(row, decision_row) -> DraftRecord:
        decision = None
        if decision_row is not None:
            decision = ApprovalDecisionRecord(
                decision_id=decision_row["id"],
                draft_id=decision_row["draft_id"],
                decision=decision_row["decision"],
                operator_id=decision_row["operator_id"],
                operator_role=decision_row["operator_role"],
                reason=decision_row["reason"],
                created_at=decision_row["created_at"],
            )
        return DraftRecord(
            draft_id=row["id"],
            incident_id=row["incident_id"],
            content=row["content"],
            status=row["status"],
            created_by=row["created_by"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            decision=decision,
        )
