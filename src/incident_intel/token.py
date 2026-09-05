import argparse
import os

from incident_intel.auth import OperatorClaims, issue_token


def main() -> None:
    parser = argparse.ArgumentParser(description="Issue a local synthetic operator token.")
    parser.add_argument("--role", choices=("viewer", "operator", "admin"), required=True)
    parser.add_argument("--operator-id", required=True)
    arguments = parser.parse_args()
    secret = os.environ.get("INCIDENT_INTEL_TOKEN_SECRET", "")
    if not secret:
        raise ValueError("INCIDENT_INTEL_TOKEN_SECRET is required")
    print(
        issue_token(
            OperatorClaims(
                operator_id=arguments.operator_id,
                role=arguments.role,
            ),
            secret=secret,
        )
    )


if __name__ == "__main__":
    main()
