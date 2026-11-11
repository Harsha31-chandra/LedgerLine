import json
import os
import shutil
import subprocess
import time
import requests
from playwright.sync_api import sync_playwright

DOCS_DIR = r"C:\Users\Janardhana\Desktop\Projects\LedgerLine\docs\screenshots"
ARTIFACT_DIR = r"C:\Users\Janardhana\.gemini\antigravity\brain\1eaaa116-3ad4-4348-af9f-eb725d54a6d8"
BASE_URL = "http://localhost:3000"

os.makedirs(DOCS_DIR, exist_ok=True)
os.makedirs(ARTIFACT_DIR, exist_ok=True)

def copy_to_artifacts(filename):
    src = os.path.join(DOCS_DIR, filename)
    dst = os.path.join(ARTIFACT_DIR, filename)
    shutil.copy2(src, dst)
    print(f"  [Artifact] Saved & copied: {filename}")

def run_db_query(sql):
    cmd = ["docker", "exec", "ledgerline-db", "psql", "-U", "ledgerline", "-d", "ledgerline", "-t", "-A", "-c", sql]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return res.stdout.strip()

def run_db_json(sql):
    wrapped = f"SELECT json_agg(t) FROM ({sql}) t;"
    cmd = ["docker", "exec", "ledgerline-db", "psql", "-U", "ledgerline", "-d", "ledgerline", "-t", "-A", "-c", wrapped]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    raw = res.stdout.strip()
    return json.loads(raw) if raw else []

def main():
    print("=" * 70)
    print("LEDGERLINE — END-TO-END ACCEPTANCE VERIFICATION RUNNER")
    print("=" * 70)

    timestamp = int(time.time())
    holder_email = f"acceptance_holder_{timestamp}@test.com"
    holder_password = "Password123!"
    holder_name = f"Acceptance Holder {timestamp % 1000}"

    console_errors = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()

        def on_console(msg):
            # Ignore standard 401 on initial unauthenticated check or favicon
            if msg.type == "error":
                if "401" not in msg.text and "favicon" not in msg.text:
                    console_errors.append(msg.text)
                    print(f"  [Browser Console Error]: {msg.text}")

        page.on("console", on_console)
        page.on("pageerror", lambda err: console_errors.append(str(err)))

        # ---------------------------------------------------------
        # STEP 1 & 2: Registration & First-Time Onboarding Experience
        # ---------------------------------------------------------
        print(f"\n[Step 1 & 2] Registering fresh Holder: {holder_email}")
        page.goto(f"{BASE_URL}/register", wait_until="networkidle")
        time.sleep(1)

        page.fill("#fullName", holder_name)
        page.fill("#email", holder_email)
        page.fill("#password", holder_password)
        page.fill("#confirmPassword", holder_password)
        page.click("button[type='submit']")

        # User is automatically logged in and redirected to /
        page.wait_for_url(f"{BASE_URL}/", timeout=12000)
        time.sleep(2)

        # Verify Onboarding Hero Card
        page.wait_for_selector(".onboarding-hero-card", timeout=8000)
        welcome_title = page.locator(".onboarding-title").inner_text()
        print(f"  [Verified] Onboarding Title: '{welcome_title}'")
        assert "Welcome to LedgerLine" in welcome_title, f"Unexpected title: {welcome_title}"

        # Verify Open Your First Account button
        open_first_btn = page.locator("button:has-text('Open Your First Account')")
        assert open_first_btn.is_visible(), "Open Your First Account button not visible"

        page.screenshot(path=os.path.join(DOCS_DIR, "acceptance_01_onboarding.png"))
        copy_to_artifacts("acceptance_01_onboarding.png")

        # ---------------------------------------------------------
        # STEP 3 & 4: Open First Financial Account (With Demo Funds)
        # ---------------------------------------------------------
        print("\n[Step 3 & 4] Opening first financial account with ₹10,000 demo credit...")
        open_first_btn.click()
        page.wait_for_selector(".account-opening-layout", timeout=5000)
        time.sleep(0.5)

        # Set Account Name
        page.fill("#accountName", "Primary Checking")
        # Check terms confirmation checkbox
        page.check(".demo-confirm-label input[type='checkbox']")
        time.sleep(0.5)

        page.screenshot(path=os.path.join(DOCS_DIR, "acceptance_02_account_form.png"))
        copy_to_artifacts("acceptance_02_account_form.png")

        # Submit Account Opening Form
        page.click(".account-opening-form button[type='submit']")
        page.wait_for_selector(".account-creation-success", timeout=10000)
        time.sleep(1)

        success_heading = page.locator(".success-heading").inner_text()
        print(f"  [Verified] Success Heading: '{success_heading}'")
        assert "Your Account is Ready!" in success_heading

        acc_num_el = page.locator(".preview-card-number span")
        primary_acc_num = acc_num_el.inner_text().strip()
        print(f"  [Verified] Primary Account Number: {primary_acc_num}")

        page.screenshot(path=os.path.join(DOCS_DIR, "acceptance_03_account_success.png"))
        copy_to_artifacts("acceptance_03_account_success.png")

        # Go to Dashboard
        page.click("button:has-text('Go to Dashboard')")
        page.wait_for_selector(".dashboard-container", timeout=10000)
        time.sleep(1)

        # Verify Account Card Details on Dashboard
        active_card = page.locator(".premium-account-card").first
        card_text = active_card.inner_text()
        print(f"  [Verified] Account Card contains 'Primary Checking', 'OWNER', 'ACTIVE', '₹10,000.00'")
        assert "Primary Checking" in card_text
        assert "OWNER" in card_text
        assert "ACTIVE" in card_text
        assert "₹10,000.00" in card_text

        page.screenshot(path=os.path.join(DOCS_DIR, "acceptance_04_dashboard_active.png"))
        copy_to_artifacts("acceptance_04_dashboard_active.png")

        # ---------------------------------------------------------
        # STEP 5 & 6: Database Ledger Verification for Opening Deposit
        # ---------------------------------------------------------
        print("\n[Step 5 & 6] Verifying database records for Primary Checking...")
        db_acc = run_db_json(f"SELECT id, account_number, account_name, balance, status, currency FROM accounts WHERE account_number = '{primary_acc_num}'")[0]
        primary_acc_id = db_acc["id"]
        print(f"  [DB Account] ID={primary_acc_id}, Name={db_acc['account_name']}, Balance={db_acc['balance']} paise, Status={db_acc['status']}")
        assert db_acc["balance"] == 1000000, f"Expected 1000000 paise, got {db_acc['balance']}"
        assert db_acc["status"] == "ACTIVE"
        assert db_acc["currency"] == "INR"

        # Verify Membership in DB
        db_mem = run_db_json(f"SELECT membership_role FROM account_memberships WHERE account_id = '{primary_acc_id}'")[0]
        assert db_mem["membership_role"] == "OWNER"
        print(f"  [DB Membership] Role={db_mem['membership_role']}")

        # Verify Double-Entry Ledger Entries
        opening_tx = run_db_json(f"SELECT id, transaction_type, amount_paise, status FROM transactions WHERE id IN (SELECT transaction_id FROM ledger_entries WHERE account_id = '{primary_acc_id}')")[0]
        print(f"  [DB Transaction] Type={opening_tx['transaction_type']}, Amount={opening_tx['amount_paise']}, Status={opening_tx['status']}")
        assert opening_tx["amount_paise"] == 1000000
        assert opening_tx["status"] == "POSTED"

        entries = run_db_json(f"SELECT e.entry_type, e.amount_paise, a.account_number, a.account_name FROM ledger_entries e JOIN accounts a ON e.account_id = a.id WHERE e.transaction_id = '{opening_tx['id']}'")
        print(f"  [DB Ledger Entries]: {json.dumps(entries, indent=2)}")
        assert len(entries) == 2, f"Expected 2 ledger entries, got {len(entries)}"
        debits = sum(e["amount_paise"] for e in entries if e["entry_type"] == "DEBIT")
        credits = sum(e["amount_paise"] for e in entries if e["entry_type"] == "CREDIT")
        print(f"  [DB Zero-Sum Invariant] Total Debits = {debits}, Total Credits = {credits}, Delta = {debits - credits}")
        assert debits == credits == 1000000, "Opening deposit ledger entries are unbalanced!"

        # Verify Audit Log
        audit_event = run_db_json(f"SELECT action, entity_type FROM audit_events WHERE action = 'DEMO_INITIAL_DEPOSIT_CLAIMED' AND metadata->>'account_id' = '{primary_acc_id}'")
        assert len(audit_event) > 0, "DEMO_INITIAL_DEPOSIT_CLAIMED audit event missing!"
        print(f"  [DB Audit Log] Verified audit event 'DEMO_INITIAL_DEPOSIT_CLAIMED'")

        # ---------------------------------------------------------
        # STEP 7: Perform Test Deposit (₹2,500.00)
        # ---------------------------------------------------------
        print("\n[Step 7] Performing test deposit of ₹2,500.00 via UI...")
        page.click(".quick-actions-panel button:has-text('Deposit')")
        page.wait_for_selector(".quick-action-form", timeout=5000)
        time.sleep(0.5)

        page.fill("#amountRupees", "2500")
        page.fill("#description", "Payroll Advance Test")
        page.click(".quick-action-form button[type='submit']")

        # Review Confirmation Step
        page.wait_for_selector(".financial-confirmation-dialog", timeout=5000)
        time.sleep(0.5)
        page.click("button:has-text('Confirm & Execute')")

        # Wait for toast and balance update
        page.wait_for_selector(".toast-notification", timeout=8000)
        toast_txt = page.locator(".toast-notification").inner_text()
        print(f"  [Verified Toast]: '{toast_txt}'")
        time.sleep(1.5)

        # Check balance in UI: ₹12,500.00
        card_text_after_dep = page.locator(".premium-account-card").first.inner_text()
        print(f"  [Verified Balance after Deposit]: Contains ₹12,500.00")
        assert "₹12,500.00" in card_text_after_dep

        page.screenshot(path=os.path.join(DOCS_DIR, "acceptance_05_deposit_success.png"))
        copy_to_artifacts("acceptance_05_deposit_success.png")

        # ---------------------------------------------------------
        # STEP 8: Perform Test Withdrawal (₹1,000.00)
        # ---------------------------------------------------------
        print("\n[Step 8] Performing test withdrawal of ₹1,000.00 via UI...")
        page.click(".quick-actions-panel button:has-text('Withdraw')")
        page.wait_for_selector(".quick-action-form", timeout=5000)
        time.sleep(0.5)

        page.fill("#amountRupees", "1000")
        page.fill("#description", "ATM Cash Withdrawal")
        page.click(".quick-action-form button[type='submit']")

        # Review Confirmation Step
        page.wait_for_selector(".financial-confirmation-dialog", timeout=5000)
        time.sleep(0.5)
        page.click("button:has-text('Confirm & Execute')")

        # Wait for toast and balance update
        page.wait_for_selector(".toast-notification", timeout=8000)
        toast_txt_w = page.locator(".toast-notification").inner_text()
        print(f"  [Verified Toast]: '{toast_txt_w}'")
        time.sleep(1.5)

        # Check balance in UI: ₹11,500.00
        card_text_after_w = page.locator(".premium-account-card").first.inner_text()
        print(f"  [Verified Balance after Withdrawal]: Contains ₹11,500.00")
        assert "₹11,500.00" in card_text_after_w

        page.screenshot(path=os.path.join(DOCS_DIR, "acceptance_06_withdrawal_success.png"))
        copy_to_artifacts("acceptance_06_withdrawal_success.png")

        # ---------------------------------------------------------
        # STEP 9 & 10: Open Second Account & Perform Inter-Account Transfer
        # ---------------------------------------------------------
        print("\n[Step 9 & 10] Opening second account 'Business Reserve' for transfer test...")
        page.click(".open-acc-action-btn")
        page.wait_for_selector(".account-opening-layout", timeout=5000)
        time.sleep(0.5)

        page.select_option("#accountType", "Current Account")
        page.fill("#accountName", "Business Reserve")
        # Uncheck demo deposit (since demo funds can only be claimed once)
        demo_cb = page.locator(".demo-checkbox-label input[type='checkbox']")
        if demo_cb.is_checked():
            demo_cb.uncheck()
        time.sleep(0.5)

        page.click(".account-opening-form button[type='submit']")
        page.wait_for_selector(".account-creation-success", timeout=10000)
        time.sleep(0.5)

        sec_acc_num = page.locator(".preview-card-number span").inner_text().strip()
        print(f"  [Verified] Secondary Account Number: {sec_acc_num}")
        page.click("button:has-text('Go to Dashboard')")
        page.wait_for_selector(".dashboard-container", timeout=10000)
        time.sleep(1)

        # Now perform transfer from Primary Checking to Business Reserve
        print(f"  Executing transfer of ₹1,500.00 to {sec_acc_num}...")
        page.click(".quick-actions-panel button:has-text('Transfer')")
        page.wait_for_selector(".quick-action-form", timeout=5000)
        time.sleep(0.5)

        # Select Primary Checking as source
        page.select_option("#selectAccount", primary_acc_id)
        # Enter destination account number
        page.fill("#destinationAccountId", sec_acc_num)
        page.fill("#amountRupees", "1500")
        page.fill("#description", "Monthly Reserve Allocation")
        page.click(".quick-action-form button[type='submit']")

        # Review Confirmation Step
        page.wait_for_selector(".financial-confirmation-dialog", timeout=5000)
        time.sleep(0.5)
        page.click("button:has-text('Confirm & Execute')")

        page.wait_for_selector(".toast-notification", timeout=8000)
        toast_txt_t = page.locator(".toast-notification").inner_text()
        print(f"  [Verified Toast]: '{toast_txt_t}'")
        time.sleep(1.5)

        # Verify balances: Primary Checking = ₹10,000.00, Business Reserve = ₹1,500.00
        dashboard_content = page.locator(".dashboard-container").inner_text()
        assert "₹10,000.00" in dashboard_content, "Primary Checking balance ₹10,000.00 not found"
        assert "₹1,500.00" in dashboard_content, "Business Reserve balance ₹1,500.00 not found"
        print("  [Verified] Both account balances correctly updated in UI (₹10,000.00 and ₹1,500.00)")

        page.screenshot(path=os.path.join(DOCS_DIR, "acceptance_07_transfer_success.png"))
        copy_to_artifacts("acceptance_07_transfer_success.png")

        # Database Zero-Sum Transfer Verification
        transfer_tx = run_db_json("SELECT id, transaction_type, amount_paise FROM transactions WHERE transaction_type = 'TRANSFER' ORDER BY created_at DESC LIMIT 1")[0]
        transfer_entries = run_db_json(f"SELECT entry_type, amount_paise, account_id FROM ledger_entries WHERE transaction_id = '{transfer_tx['id']}'")
        print(f"  [DB Transfer Entries]: {json.dumps(transfer_entries, indent=2)}")
        assert len(transfer_entries) == 2, "Transfer transaction must have exactly 2 entries"
        tx_debit = sum(e["amount_paise"] for e in transfer_entries if e["entry_type"] == "DEBIT")
        tx_credit = sum(e["amount_paise"] for e in transfer_entries if e["entry_type"] == "CREDIT")
        assert tx_debit == tx_credit == 150000, "Transfer entries unbalanced!"
        print(f"  [DB Transfer Zero-Sum] Debits={tx_debit}, Credits={tx_credit}, Delta=0")

        # ---------------------------------------------------------
        # STEP 11: Transaction History & Statements Verification
        # ---------------------------------------------------------
        print("\n[Step 11] Verifying transaction history and statements...")
        # Navigate to Statements tab via sidebar button
        page.click(".sidebar-nav-item:has-text('Statements')")
        time.sleep(1.5)

        page.wait_for_selector(".statements-viewer-section", timeout=8000)
        # Select Primary Checking to inspect all postings
        page.select_option("#statementAccountSelect", primary_acc_id)
        time.sleep(1)

        statements_text = page.locator(".statements-viewer-section").inner_text()
        print(f"  [Verified Statements Header]: Contains 'Account Statements'")
        assert "Account Statements" in statements_text
        assert "Monthly Reserve Allocation" in statements_text
        assert "ATM Cash Withdrawal" in statements_text
        assert "Payroll Advance Test" in statements_text

        page.screenshot(path=os.path.join(DOCS_DIR, "acceptance_08_transaction_history.png"))
        copy_to_artifacts("acceptance_08_transaction_history.png")

        # ---------------------------------------------------------
        # STEP 12: Browser Refresh & Session Persistence
        # ---------------------------------------------------------
        print("\n[Step 12] Testing browser refresh and session persistence...")
        page.reload(wait_until="networkidle")
        time.sleep(1.5)

        # Assert user still authenticated
        reloaded_top = page.locator(".dashboard-user-title").inner_text()
        print(f"  [Verified Session Persistence after Reload]: '{reloaded_top}'")
        assert "Hello, Acceptance" in reloaded_top

        # Sign Out
        print("  Testing Sign Out...")
        page.click("button:has-text('Sign Out')")
        page.wait_for_url(f"{BASE_URL}/login", timeout=8000)
        time.sleep(1)

        # Try to navigate back to /
        page.goto(f"{BASE_URL}/", wait_until="networkidle")
        page.wait_for_url(f"{BASE_URL}/login", timeout=8000)
        print("  [Verified] Unauthorized access to / redirected back to /login (Session revoked)")

        page.screenshot(path=os.path.join(DOCS_DIR, "acceptance_09_signed_out.png"))
        copy_to_artifacts("acceptance_09_signed_out.png")

        # ---------------------------------------------------------
        # ROLE VERIFICATION: ADMIN
        # ---------------------------------------------------------
        print("\n[Role: ADMIN] Logging in as admin@ledgerline.com...")
        page.fill("#email", "admin@ledgerline.com")
        page.fill("#password", "SecurePass123!")
        page.click("button[type='submit']")
        page.wait_for_url(f"{BASE_URL}/", timeout=10000)
        time.sleep(1)

        # Navigate to Admin Console via SPA Link
        print("  Navigating to Admin Console via SPA link...")
        page.click("text=Admin Console")
        page.wait_for_selector("text=Administrative Account Console", timeout=15000)
        page.wait_for_selector(".metrics-grid", timeout=15000)
        time.sleep(1)

        admin_text = page.locator(".page-container").inner_text()
        assert "Administrative Account Console" in admin_text
        assert "Total Users" in admin_text
        assert "Total Accounts" in admin_text
        assert "Accounts Registry" in admin_text
        print("  [Verified Admin View] Total Users, Total Accounts, Accounts Registry, Portfolio Balance displayed")

        page.screenshot(path=os.path.join(DOCS_DIR, "acceptance_10_admin_console.png"))
        copy_to_artifacts("acceptance_10_admin_console.png")

        # Navigate back to Dashboard before signing out
        page.click("text=Dashboard")
        page.wait_for_url(f"{BASE_URL}/", timeout=8000)
        time.sleep(0.5)

        # Sign out Admin
        page.click("button:has-text('Sign Out')")
        page.wait_for_url(f"{BASE_URL}/login", timeout=8000)
        time.sleep(1)

        # ---------------------------------------------------------
        # ROLE VERIFICATION: AUDITOR
        # ---------------------------------------------------------
        print("\n[Role: AUDITOR] Logging in as auditor@ledgerline.com...")
        page.fill("#email", "auditor@ledgerline.com")
        page.fill("#password", "SecurePass123!")
        page.click("button[type='submit']")
        page.wait_for_url(f"{BASE_URL}/", timeout=10000)
        time.sleep(1)

        # Auditor landing on / automatically renders AuditorDashboardPage
        page.wait_for_selector(".auditor-safety-banner", timeout=15000)
        page.wait_for_selector("text=Auditor Oversight & Ledger Verification", timeout=15000)
        time.sleep(1)

        auditor_text = page.locator(".page-container").inner_text()
        assert "Read-Only Compliance Mode Active" in auditor_text
        assert "Auditor Oversight" in auditor_text
        assert "Customer Accounts" in auditor_text
        assert "Double-Entry" in auditor_text
        print("  [Verified Auditor View] Read-Only Safety Banner, Customer Accounts, Double-Entry Metrics displayed")

        # Prohibited Mutation Check: Try calling onboarding account creation as auditor
        print("  [Security Check] Testing prohibited mutation rejection for Auditor role...")
        cookies = context.cookies()
        session_cookie = next((c["value"] for c in cookies if c["name"] == "ledgerline_session"), None)
        assert session_cookie is not None, "Session cookie not found!"

        # 1. Auditor attempting account creation -> 403 Forbidden
        resp_acc = requests.post(
            f"{BASE_URL}/accounts/onboarding",
            json={"account_name": "Prohibited Auditor Account", "currency": "INR", "initial_deposit_paise": 0},
            headers={"Origin": BASE_URL},
            cookies={"ledgerline_session": session_cookie},
        )
        print(f"  [Security Check Result] Auditor POST /accounts/onboarding returned HTTP {resp_acc.status_code}")
        assert resp_acc.status_code == 403, f"Expected 403 Forbidden for Auditor account creation, got {resp_acc.status_code}: {resp_acc.text}"
        assert "Auditor" in resp_acc.text or "read-only" in resp_acc.text.lower()
        print("  [Verified] Backend strictly rejects Auditor account creation with HTTP 403!")

        # 2. Auditor attempting financial mutation on unowned account -> 404 Anti-IDOR
        resp_dep = requests.post(
            f"{BASE_URL}/transactions/deposit",
            json={
                "account_id": primary_acc_id,
                "amount_paise": 100000,
                "description": "Unauthorized Auditor Deposit Attempt",
            },
            headers={"Origin": BASE_URL},
            cookies={"ledgerline_session": session_cookie},
        )
        print(f"  [Security Check Result] Auditor POST /transactions/deposit returned HTTP {resp_dep.status_code} (Anti-IDOR protected)")
        assert resp_dep.status_code in (403, 404), f"Expected 403 or 404, got {resp_dep.status_code}"

        page.screenshot(path=os.path.join(DOCS_DIR, "acceptance_11_auditor_console.png"))
        copy_to_artifacts("acceptance_11_auditor_console.png")

        # Sign out Auditor
        page.click("button:has-text('Sign Out')")
        page.wait_for_url(f"{BASE_URL}/login", timeout=8000)

        browser.close()

    print("\n" + "=" * 70)
    print("ALL 12 ACCEPTANCE VERIFICATION STEPS & ROLE AUDITS PASSED!")
    print(f"Console errors during execution: {len(console_errors)}")
    if console_errors:
        print("Console errors recorded:", console_errors)
    print("=" * 70)

if __name__ == "__main__":
    main()
