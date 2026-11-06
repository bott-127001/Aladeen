import time
from playwright.sync_api import sync_playwright

def read_response():
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp("http://127.0.0.1:9223")
        target_page = None
        for ctx in browser.contexts:
            for page in ctx.pages:
                if "b501f216-c18a-4ce9-b16b-4f4ec06aca28" in page.url:
                    target_page = page
                    break
            if target_page:
                break

        if not target_page:
            print("Target page not found!")
            return

        prose_blocks = target_page.locator(".prose").all()
        print(f"Total prose blocks: {len(prose_blocks)}")
        if prose_blocks:
            latest_prose = prose_blocks[-1]
            text = latest_prose.inner_text()
            print("=== LATEST PROSE BLOCK ===")
            print(text[:500] + ("..." if len(text) > 500 else ""))
            with open("perplexity_handoff_080_response.txt", "w", encoding="utf-8") as f:
                f.write(text)
            print("Saved to perplexity_handoff_080_response.txt")

if __name__ == "__main__":
    read_response()
