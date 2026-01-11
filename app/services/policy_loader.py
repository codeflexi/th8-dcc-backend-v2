from pathlib import Path
import yaml

BASE_DIR = Path(__file__).resolve().parents[1]
POLICY_DIR = BASE_DIR / "policies"


class PolicyLoader:
    """
    Load policy YAML by explicit filename mapping
    """

    POLICY_FILE_MAP = {
        "PROCUREMENT-001": "procurement_policy_v3.yaml",
        "PRICING-001": "pricing_policy_v1.yaml",
        "CREDIT-001": "credit_policy_v1.yaml",
    }

    @staticmethod
    def load(policy_id: str, version: str) -> dict:
        if policy_id not in PolicyLoader.POLICY_FILE_MAP:
            raise FileNotFoundError(f"Unknown policy_id: {policy_id}")

        filename = PolicyLoader.POLICY_FILE_MAP[policy_id]
        policy_path = POLICY_DIR / filename

        if not policy_path.exists():
            raise FileNotFoundError(f"Policy file not found: {filename}")

        with open(policy_path, "r") as f:
            policy = yaml.safe_load(f)

        policy["_meta"] = {
            "policy_id": policy["policy_id"],
            "version": policy["version"],
            "source_file": filename,
        }

        return policy
