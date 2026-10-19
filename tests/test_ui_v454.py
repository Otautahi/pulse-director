"""Offline UI regression checks. No network or device commands."""
import hashlib
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
source = (ROOT/'edge_dashboard.py').read_text(encoding='utf-8')
html = source.split("HTML = r'''",1)[1].split("'''",1)[0]
js = html.split('<script>\n',1)[1].split('\n</script>',1)[0]

class PrivateUiSafetyTests(unittest.TestCase):
    def test_cloud_motor_and_fault_contract_remains_present(self):
        # The v4.5.5 release intentionally modifies pattern/session engine code.
        # Keep structural safety contracts instead of the old v4.5.3 hash.
        self.assertIn('CLOUD_MAX_SESSION_SECONDS = 7200', source)
        self.assertIn('CLOUD_CALLBACK_MAX_AGE_SECONDS = 90', source)
        self.assertIn('self.fault_latched',source)
        self.assertIn('physical_off is not True',source)

    def test_routine_cloud_completion_prompts_only_on_next_action(self):
        self.assertIn('s.cloudRoutineStopConfirmRequired===true',js)
        self.assertIn('const visibleFault=s.faultLatched&&(!routineCloudStop||routineConfirmExpanded)',js)
        self.assertIn("$('safetyFault').classList.toggle('hide',!visibleFault)",js)
        self.assertIn('function askRoutineConfirmation()',js)
        self.assertIn('if(askRoutineConfirmation())return',js)
        self.assertIn("$('start').disabled=!!s.faultLatched&&!routineCloudStop",js)
        self.assertIn("$('manual').disabled=!!s.faultLatched&&!routineCloudStop",js)
        self.assertIn("$('test').disabled=!!s.faultLatched&&!routineCloudStop",js)
        self.assertIn("$('ackFault').disabled=lastCloudOffRequired?!$('cloudOffConfirm').checked:!!s.stopPending",js)
        self.assertIn('physicalOffConfirmed:ok',js)
        self.assertIn('class="warning-banner safety-fault hide"',html)
        self.assertIn('routine-confirmation',html)

    def test_genuine_fault_keeps_alert(self):
        self.assertIn("routineCloudStop?'status':'alert'",js)
        self.assertIn('CONNECTION FAULT — PHYSICAL MOTOR STATE UNKNOWN',html)
        self.assertIn("s.cloudRequiresPhysicalOff?'The cloud connection or Stop needs attention",js)

    def test_cloud_limit_in_ui_with_lan_timer_retained(self):
        self.assertIn("s.connectionMode==='cloud'&&s.cloudExperimentalEnabled===true",js)
        self.assertIn("$('minutes').max='120'",js)
        self.assertIn("$('untilStopped').disabled=false",js)
        self.assertIn('id="acceptExtendedCloudRisk"',html)
        self.assertIn('id="timerHint"',html)

    def test_start_error_stays_visible_until_next_explicit_success(self):
        self.assertIn("stickyError||s.message||'Ready'",js)
        self.assertIn("$('requestError').classList.remove('hide')",js)
        self.assertIn("const s=await api(path,body);clearRequestError();display(s)",js)
        self.assertIn('id="requestError"',html)
        self.assertIn("const stopNow=async()=>",js)

if __name__ == '__main__': unittest.main()
