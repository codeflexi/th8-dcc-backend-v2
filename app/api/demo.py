from fastapi import APIRouter, Request

#from app.services.demo_loader import load_demo_data

from app.services.demo_loader import seed_demo_data


router = APIRouter(tags=["demo"])


@router.post("/demo/load")
def load_demo(request: Request):
    audit_repo = getattr(request.app.state, "audit_repo", None)
    case_repo = getattr(request.app.state, "case_repo", None)

    demo_db = seed_demo_data(audit_repo=audit_repo)
    cases = demo_db.get("cases", [])

    # ถ้ามี repo ก็ persist + CASE_LOADED (เหมือน startup)
    if case_repo and audit_repo:
        for case in cases:
            case_repo.save_case(case)
            audit_repo.append_event(
                case_id=case.get("case_id", ""),
                event_type="CASE_LOADED",
                actor="system",
                payload={
                    "domain": case.get("domain"),
                    "status": case.get("status"),
                    "sources": case.get("sources", []),
                    "trigger": "api",
                },
            )

    return {"status": "loaded", "summary": {"cases": len(cases)}}
