import sys
import os

# ✅ Hack: เพิ่ม Path ปัจจุบันเข้าไป เพื่อให้ Python มองเห็น folder 'app'
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)

from app.api.decisions import execute_decision_run
import logging

# ปิด Log ของระบบชั่วคราว เพื่อให้เห็นผล Test ชัดๆ
logging.basicConfig(level=logging.CRITICAL)

def test_logic():
    print("\n🚀 Starting Logic Verification (Safety Check)...")
    print("="*60)
    
    # ----------------------------------------------------
    # MOCK POLICY: จำลอง Policy เพื่อทดสอบ (ไม่ต้องแก้ไฟล์จริง)
    # ----------------------------------------------------
    mock_policy = {
        "policy_id": "TEST-POLICY",
        "version": "1.0",
        "config": {
            "high_risk_threshold": 200000, 
            "force_risk_level": "HIGH"
        },
        "rules": [
            {
                "id": "RULE-HIGH-VAL",
                "description": "High Value Check (> 200k)",
                "conditions": [{"field": "amount", "operator": ">", "value": 200000}]
            },
            {
                "id": "RULE-SLA",
                "description": "SLA Check (< 24h)",
                "conditions": [{"field": "hours_to_sla", "operator": "<", "value": 24}]
            }
        ]
    }

    # ==============================================================================
    # TEST CASE 1: High Value -> ต้องเจอ Risk และ Log ต้องโชว์ตัวเลขชัดเจน
    # ==============================================================================
    print("\n🧪 [CASE 1] Testing High Value Input (387,500.00)")
    
    case_high = {
        "case_id": "TEST-CASE-001",
        "payload": {
            "amount": "387,500.00", 
            "vendor_name": "Test Vendor",
            "hours_to_sla": 48
        }
    }
    
    # รันจริง
    result = execute_decision_run(
        case=case_high, 
        policy=mock_policy, 
        policy_id="TEST", 
        policy_version="1"
    )
    
    # --- VERIFY 1: Check Safety Net (Risk Level) ---
    risk_level = case_high["payload"].get("risk_level")
    if risk_level == "HIGH":
        print("   ✅ Safety Net Check: PASSED (Risk changed to HIGH)")
    else:
        print(f"   ❌ Safety Net Check: FAILED (Risk is {risk_level})")

    # --- VERIFY 2: Check Human Readable Log ---
    # เราคาดหวังให้ Log มีคำว่า "387,500.00" และ "200,000.00" และเครื่องหมาย ">"
    # เพราะเราต้องการเห็นหลักฐานทางคณิตศาสตร์
    
    found_math_evidence = False
    log_message = ""
    
    for r in result["rule_results"]:
        inputs_data = r.get("inputs", {})
        # แปลง dict เป็น string เพื่อค้นหาคำ
        inputs_str = str(inputs_data)
        
        # เช็คว่ามี Logic ของ Amount หรือไม่
        if "387,500.00" in inputs_str and "200,000.00" in inputs_str:
            found_math_evidence = True
            log_message = inputs_str
            break
            
    if found_math_evidence:
        print(f"   ✅ Smart Log Check:  PASSED")
        print(f"      Evidence Found: {log_message}")
    else:
        print(f"   ❌ Smart Log Check:  FAILED (Math evidence missing)")
        print(f"      Actual Logs: {result['rule_results']}")

    # ==============================================================================
    # TEST CASE 2: Safe Amount & SLA Pass -> ต้องแสดง Log ว่า Pass แบบเข้าใจง่าย
    # ==============================================================================
    print("\n🧪 [CASE 2] Testing Safe Logic (SLA 48h vs Rule < 24h)")
    
    case_safe = {
        "case_id": "TEST-CASE-002",
        "payload": {
            "amount": "50,000", 
            "hours_to_sla": 48  # 48 ชั่วโมง (ปลอดภัย เพราะ > 24)
        }
    }
    
    result_safe = execute_decision_run(
        case=case_safe, 
        policy=mock_policy, 
        policy_id="TEST", 
        policy_version="1"
    )
    
    # ค้นหา Log ของ SLA Rule
    found_readable_pass = False
    pass_message = ""
    
    for r in result_safe["rule_results"]:
        inputs_str = str(r.get("inputs", {}))
        # คาดหวังคำว่า "Pass" และการเปรียบเทียบ "48.00" กับ "24.00"
        if "Pass" in inputs_str and "48.00" in inputs_str and "24.00" in inputs_str:
            found_readable_pass = True
            pass_message = inputs_str
            
    if found_readable_pass:
        print(f"   ✅ Human Logic Check: PASSED")
        print(f"      Explanation: {pass_message}")
    else:
        print(f"   ❌ Human Logic Check: FAILED")
        print(f"      Actual Logs: {result_safe['rule_results']}")

    print("\n" + "="*60)
    print("🏁 FINAL VERDICT: " + ("READY FOR PRODUCTION ✅" if found_math_evidence and found_readable_pass else "DO NOT DEPLOY ❌"))

if __name__ == "__main__":
    try:
        test_logic()
    except ImportError as e:
        print(f"\n❌ IMPORT ERROR: {e}")
        print("👉 ตรวจสอบว่าวางไฟล์ verify_logic.py ไว้นอกโฟลเดอร์ 'app' หรือไม่")
    except Exception as e:
        print(f"\n❌ RUNTIME ERROR: {e}")