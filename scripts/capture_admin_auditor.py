import os
import shutil
import time
from playwright.sync_api import sync_playwright

ARTIFACT_DIR = r"C:\Users\Janardhana\.gemini\antigravity\brain\1eaaa116-3ad4-4348-af9f-eb725d54a6d8"
DOCS_DIR = r"C:\Users\Janardhana\Desktop\Projects\LedgerLine\docs\screenshots"

def copy_to_artifacts(filename):
    src = os.path.join(DOCS_DIR, filename)
    dst = os.path.join(ARTIFACT_DIR, filename)
    shutil.copy2(src, dst)
    print(f"Copied {filename} to {dst}")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(viewport={"width": 1400, "height": 900})
    page = context.new_page()

    # --- 1. ADMIN DASHBOARD FLOW ---
    print("Navigating to login page for Admin...")
    page.goto("http://localhost:3000/login", wait_until="networkidle")
    page.fill("#email", "admin@ledgerline.com")
    page.fill("#password", "SecurePass123!")
    page.click("button.btn-primary")
    page.wait_for_url("http://localhost:3000/", timeout=15000)
    print("Admin logged in successfully!")
    time.sleep(1)

    # Click Admin Console link in Navbar
    print("Navigating to Admin Console...")
    page.click("text=Admin Console")
    page.wait_for_selector("text=Administrative Account Console", timeout=15000)
    page.wait_for_selector(".metrics-grid", timeout=15000)
    time.sleep(1.5)
    page.screenshot(path=os.path.join(DOCS_DIR, "admin_dashboard.png"))
    copy_to_artifacts("admin_dashboard.png")
    print("admin_dashboard.png captured successfully!")

    # Sign out
    print("Signing out Admin...")
    page.click("button:has-text('Sign Out')")
    page.wait_for_url("http://localhost:3000/login", timeout=15000)
    time.sleep(1)

    # --- 2. AUDITOR DASHBOARD FLOW ---
    print("Logging in as Auditor...")
    page.fill("#email", "auditor@ledgerline.com")
    page.fill("#password", "SecurePass123!")
    page.click("button.btn-primary")
    page.wait_for_url("http://localhost:3000/", timeout=15000)
    print("Auditor logged in successfully!")

    # When Auditor visits /, DashboardPage renders AuditorDashboardPage directly
    page.wait_for_selector(".auditor-safety-banner", timeout=15000)
    page.wait_for_selector(".metrics-grid", timeout=15000)
    time.sleep(1.5)
    page.screenshot(path=os.path.join(DOCS_DIR, "auditor_dashboard.png"))
    copy_to_artifacts("auditor_dashboard.png")
    print("auditor_dashboard.png captured successfully!")

    browser.close()
    print("Both Admin and Auditor screenshots captured successfully!")
