import os
import shutil
import time
from playwright.sync_api import sync_playwright

ARTIFACT_DIR = r"C:\Users\Janardhana\.gemini\antigravity\brain\1eaaa116-3ad4-4348-af9f-eb725d54a6d8"
DOCS_DIR = r"C:\Users\Janardhana\Desktop\Projects\LedgerLine\docs\screenshots"

os.makedirs(DOCS_DIR, exist_ok=True)
os.makedirs(ARTIFACT_DIR, exist_ok=True)

def copy_to_artifacts(filename):
    src = os.path.join(DOCS_DIR, filename)
    dst = os.path.join(ARTIFACT_DIR, filename)
    shutil.copy2(src, dst)
    print(f"Copied {filename} to {dst}")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(viewport={"width": 1400, "height": 900})
    page = context.new_page()

    # --- PART 1: HOLDER FLOW (Modals: Deposit, Withdraw, Transfer) ---
    print("Navigating to login page for Holder flow...")
    page.goto("http://localhost:3000/login", wait_until="networkidle")

    # Use harsha_screens_v2_1794316161@test.com
    page.fill("#email", "harsha_screens_v2_1794316161@test.com")
    page.fill("#password", "Password123!")
    page.click("button[type='submit']")
    page.wait_for_url("http://localhost:3000/")
    page.wait_for_selector(".dashboard-container", timeout=10000)
    time.sleep(1)

    # 1. Deposit Screen
    print("Opening Deposit modal...")
    page.click("button:has-text('Deposit')")
    page.wait_for_selector(".modal-backdrop", timeout=5000)
    time.sleep(0.5)
    page.screenshot(path=os.path.join(DOCS_DIR, "deposit_screen.png"))
    copy_to_artifacts("deposit_screen.png")
    page.keyboard.press("Escape")
    time.sleep(0.5)

    # 2. Withdrawal Screen
    print("Opening Withdrawal modal...")
    page.click("button:has-text('Withdraw')")
    page.wait_for_selector(".modal-backdrop", timeout=5000)
    time.sleep(0.5)
    page.screenshot(path=os.path.join(DOCS_DIR, "withdrawal_screen.png"))
    copy_to_artifacts("withdrawal_screen.png")
    page.keyboard.press("Escape")
    time.sleep(0.5)

    # 3. Transfer Screen
    print("Opening Transfer modal...")
    page.click("button:has-text('Transfer')")
    page.wait_for_selector(".modal-backdrop", timeout=5000)
    time.sleep(0.5)
    page.screenshot(path=os.path.join(DOCS_DIR, "transfer_screen.png"))
    copy_to_artifacts("transfer_screen.png")
    page.keyboard.press("Escape")
    time.sleep(0.5)

    # Sign out
    print("Signing out...")
    page.click("button:has-text('Sign Out')")
    page.wait_for_url("http://localhost:3000/login")
    time.sleep(1)

    # --- PART 2: ADMIN DASHBOARD FLOW ---
    print("Logging in as Admin...")
    page.fill("#email", "admin@ledgerline.com")
    page.fill("#password", "SecurePass123!")
    page.click("button[type='submit']")
    time.sleep(1)

    # Go to Admin Console
    page.goto("http://localhost:3000/admin/accounts", wait_until="networkidle")
    page.wait_for_selector("text=Administrative Account Console", timeout=10000)
    time.sleep(1)
    page.screenshot(path=os.path.join(DOCS_DIR, "admin_dashboard.png"))
    copy_to_artifacts("admin_dashboard.png")

    # Sign out
    print("Signing out Admin...")
    page.click("button:has-text('Sign Out')")
    page.wait_for_url("http://localhost:3000/login")
    time.sleep(1)

    # --- PART 3: AUDITOR DASHBOARD FLOW ---
    print("Logging in as Auditor...")
    page.fill("#email", "auditor@ledgerline.com")
    page.fill("#password", "SecurePass123!")
    page.click("button[type='submit']")
    time.sleep(1)

    # Go to Auditor Console
    page.goto("http://localhost:3000/audit", wait_until="networkidle")
    page.wait_for_selector("text=Auditor Oversight & Ledger Verification", timeout=10000)
    time.sleep(1)
    page.screenshot(path=os.path.join(DOCS_DIR, "auditor_dashboard.png"))
    copy_to_artifacts("auditor_dashboard.png")

    browser.close()
    print("All screenshots successfully captured!")
