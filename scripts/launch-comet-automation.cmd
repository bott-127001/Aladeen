@echo off
echo Starting Comet automation instance on port 9223...
start "" "C:\Program Files\Perplexity\Comet\Application\comet.exe" --user-data-dir="C:\Users\samar\.comet-automation-profile" --remote-debugging-port=9223 --remote-debugging-address=127.0.0.1 --no-first-run --no-default-browser-check "https://www.perplexity.ai/"
echo Comet launched. Endpoint will be available at http://127.0.0.1:9223
