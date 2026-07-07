@echo off
REM Register a daily 06:00 Windows Task Scheduler job that runs the update.
REM Run this once from an elevated (Administrator) command prompt.
REM Only needed if you set MW_ENABLE_SCHEDULER=0; by default the web server
REM updates itself in-process and no Task Scheduler job is required.
schtasks /Create /TN "MarketBigPictureWatch Daily Update" ^
  /TR "\"%~dp0update_data.bat\"" /SC DAILY /ST 06:00 /F
echo Done. Verify with: schtasks /Query /TN "MarketBigPictureWatch Daily Update"
