# Worker App - Advanced Features Guide

## 🚀 New Features Overview

The worker app now includes several advanced features to improve reliability, reduce resource usage, and provide better user experience.

---

## 1. 📍 System Tray Integration

### What It Does
- **Hides the app** from taskbar to system tray (hidden icons area)
- Provides **quick access menu** for common actions
- Keeps app running in background

### How to Use

**Hide/Show Window:**
- Click the tray icon to toggle window visibility
- Or use tray menu: "Show/Hide Window"

**Quick Actions from Tray:**
- ⏯ **Clock In** - Start working session
- ⏹ **Clock Out** - End working session
- ❌ **Quit** - Exit application

### Tray Menu Options
```
[Show/Hide Window]  ← Toggle window visibility
[Clock In]          ← Start work session
[Clock Out]         ← End work session
─────────────────
[Quit]              ← Exit app
```

### Benefits
- ✅ **Less distracting** - App runs quietly in background
- ✅ **Quick access** - Control without opening window
- ✅ **Professional** - Looks like native Windows app

---

## 2. ⚡ Auto Check-In on Startup

### What It Does
- Automatically **clocks you in** when app starts
- **No manual action** needed after login
- Perfect for daily routine - just start app and work
- **Auto-registers in Windows startup** after first successful login

### How It Works

```
App Starts (or Windows Startup)
    ↓
Login (saved credentials)
    ↓
Wait 2 seconds
    ↓
Auto Clock In ✅
    ↓
Start monitoring (screenshots, activity)
    ↓
Register in Windows Startup Registry ✅
```

### Windows Startup Registration

**After First Login:**
- App adds itself to `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`
- Registry key: `WorkerActivityTracker`
- Points to the app's executable path
- Shows toast notification: "Will run on Windows startup"

**Benefits:**
- ✅ App starts automatically when Windows boots
- ✅ Auto-login with saved credentials
- ✅ Auto clock-in after 2 seconds
- ✅ No manual intervention needed

### Example Scenario
1. You turn on your PC in the morning
2. Worker app starts automatically (from startup registry)
3. App logs you in with saved credentials
4. **After 2 seconds, you're automatically clocked in!**
5. Screenshot capture starts immediately
6. Toast confirms: "Auto clocked in on startup!"

### Configuration
- Only works if **not already clocked in**
- Only works with **saved credentials**
- Can be disabled by setting env var: `AUTO_CHECK_IN=false`

---

## 2.5 📊 Real-Time Screenshot Delay Tracking

### What It Does
- **Tracks screenshot count** vs expected count
- **Calculates delay** if interval changes during work
- **Sends delay info** with every screenshot upload
- **Logs delay status** to console

### How It Works

**Clock-In:**
```
User Clocks In
    ↓
Reset counters:
  - screenshot_count = 0
  - expected_screenshot_count = 0
  - delay_count = 0
  - session_start_for_delay = now
```

**During Work:**
```
Every 5 minutes (or configured interval):
    ↓
Capture screenshot
    ↓
Increment screenshot_count
    ↓
Calculate expected: elapsed_seconds / interval
    ↓
Calculate delay: expected - actual
    ↓
Send with upload:
  - screenshot_count
  - expected_screenshot_count
  - delay_count
  - delay_seconds
```

### Console Output Examples

**On Schedule:**
```
Screenshot #10 uploaded for worker WRK001 - Size: 180.5KB (On schedule)
```

**Behind Schedule:**
```
[Screenshot Delay] Behind by 3 screenshots (900s delay)
Screenshot #12 uploaded for worker WRK001 - Size: 175.2KB (Delay: 3 screenshots, 900s)
```

**Every 10 Screenshots (Status Update):**
```
[Screenshot Status] 20 captured, on schedule
```

### Scenario: Interval Changed During Work

**Example:**
```
9:00 AM - Clock in, interval = 300s (5 min)
9:05 AM - Screenshot #1 (expected: 1, actual: 1) ✅
9:10 AM - Screenshot #2 (expected: 2, actual: 2) ✅
9:12 AM - Admin changes interval to 120s (2 min)
9:15 AM - Screenshot #3 (expected: 4, actual: 3) ⚠️ Delay: 1
9:17 AM - Screenshot #4 (expected: 6, actual: 4) ⚠️ Delay: 2
9:19 AM - Screenshot #5 (expected: 8, actual: 5) ⚠️ Delay: 3
```

### Server-Side Storage

Database stores delay metrics per screenshot:
```sql
screenshot_count: 15
expected_screenshot_count: 18
delay_count: 3
delay_seconds: 900
```

### Benefits
- ✅ **Real-time monitoring** - See delays immediately
- ✅ **Interval change detection** - Tracks when interval changes
- ✅ **Performance metrics** - Admin can see worker delays
- ✅ **Automatic calculation** - No manual tracking needed
- ✅ **Database persistence** - All delay data stored for analysis

---

## 3. 🛡️ Auto Checkout on Crash/Close/Shutdown

### What It Does
- If you **close the window** while clocked in → **auto clock out**
- If app **crashes** → Uses last screenshot time as checkout
- If **PC shuts down** → **Auto clock out** before shutdown completes
- **Never loses track** of your work session

### How It Works

**Window Closed:**
```
Window Closed
    ↓
Check: Is user clocked in? 
    ↓ YES
Get last screenshot timestamp
    ↓
Clock out with that timestamp
    ↓
Flush all pending activity logs
    ↓
Session ended properly ✅
```

**PC Shutting Down:**
```
Windows Shutdown Detected
    ↓
Check: Is user clocked in?
    ↓ YES
Get last screenshot timestamp
    ↓
Flush all pending activity logs
    ↓
Send clock-out request to API
    ↓
If fails → Queue for retry on next startup
    ↓
Stop monitoring and tray
    ↓
Allow Windows shutdown to proceed ✅
```

### Windows Shutdown Handler

**Implementation Details:**
- Uses Windows `WM_QUERYENDSESSION` and `WM_ENDSESSION` messages
- Intercepts shutdown event using window procedure hook
- Performs checkout **immediately** when shutdown detected
- Uses short API timeout (system shutting down)
- If checkout fails → Queues for retry on next startup
- Returns `TRUE` to allow shutdown to proceed

**Example Console Output:**
```
[Shutdown] Windows shutdown detected (msg=0x11)
[Shutdown] PC shutting down - performing auto checkout...
[Shutdown] Checkout time: 2026-04-14T15:45:30
[Batch Flush] Flushing 15 pending activity logs...
[Shutdown] Checkout successful
[Shutdown] Auto checkout complete
```

### Last Screenshot Timestamp
- Every screenshot is **timestamped**
- When clocking out automatically, uses that time
- **Accurate session tracking** even on crash/shutdown

### Example
```
Last screenshot: 2:45:30 PM
Window closed:   2:47:00 PM
PC shutdown:     2:50:00 PM
Checkout time:   2:45:30 PM (from screenshot)
```

### Benefits
- ✅ **No forgotten sessions** - Always ends properly
- ✅ **Accurate timestamps** - Based on actual activity
- ✅ **Crash recovery** - Even if app crashes, session ends
- ✅ **Shutdown protection** - PC shutdown won't lose data
- ✅ **Retry on failure** - Queued if API unavailable

---

## 4. 📦 Screenshot Compression (200KB Max)

### What It Does
- **Compresses screenshots** to maximum 200KB
- Uses **JPEG format** with smart quality adjustment
- **Saves bandwidth** and server storage

### Compression Algorithm

```
Screenshot captured
    ↓
Apply watermark
    ↓
Convert to RGB (for JPEG)
    ↓
Scale to max 720px height
    ↓
Try quality: 85%
    ↓
Check file size
    ↓
If > 200KB → Reduce quality by 5%
    ↓
Repeat until ≤ 200KB
    ↓
If still too large → Scale width to 1280px
    ↓
Upload compressed image
```

### Quality Settings
- **Starting quality:** 85%
- **Minimum quality:** 40%
- **Max dimensions:** 1280x720
- **Target size:** ≤ 200KB

### Benefits
- ✅ **Smaller files** - ~200KB vs ~2MB PNG
- ✅ **Faster uploads** - 10x faster
- ✅ **Less storage** - Server saves 90% space
- ✅ **Still clear** - Quality is good for monitoring

### Example
```
Original PNG: 2.5 MB (1920x1080)
Compressed:   180 KB (1280x720, JPEG 75%)
Reduction:    93% smaller!
```

### Configuration
```env
# Set custom max size (in KB)
MAX_SCREENSHOT_SIZE_KB=200
```

---

## 5. 📊 Batch Activity Log Flush

### What It Does
- **Queues all activity logs** during session
- **Flushes in one API call** on clock-out
- **Reduces server load** significantly

### How It Works

**During Session:**
```
Activity change detected
    ↓
Queue activity segment
    ↓
Continue working...
    ↓
Another activity change
    ↓
Queue another segment
    ↓
Repeat...
```

**On Clock-Out:**
```
Clock out triggered
    ↓
Collect all queued segments
    ↓
Single API call with ALL segments
    ↓
Server processes batch
    ↓
All activity logged ✅
```

### Batch API Endpoint
```
POST /api/worker-event/activity-segment-batch

{
  "worker_id": "WRK001",
  "work_session_id": 123,
  "activity_segments": [
    {
      "started_at": "2026-04-14T09:00:00",
      "ended_at": "2026-04-14T09:15:00",
      "duration_seconds": 900,
      "app_name": "chrome.exe",
      "browser_name": "Chrome",
      "browser_domain": "github.com"
    },
    {
      "started_at": "2026-04-14T09:15:00",
      "ended_at": "2026-04-14T09:30:00",
      "duration_seconds": 900,
      "app_name": "code.exe",
      "window_title": "Visual Studio Code"
    },
    ... more segments
  ]
}
```

### Benefits
- ✅ **Fewer API calls** - 1 instead of 50+
- ✅ **Less network traffic** - 95% reduction
- ✅ **Better performance** - App feels snappier
- ✅ **Server friendly** - Single transaction

### Example
```
Without batch:   50 API calls during 8-hour day
With batch:      1 API call at end of day
Reduction:       98% fewer calls!
```

---

## 6. 🎯 System Tray Clock Controls

### What It Does
- **Clock in/out directly** from system tray
- **No need to open window** for basic actions
- Shows window briefly for confirmation

### How It Works

**Clock In from Tray:**
1. Right-click tray icon
2. Click "Clock In"
3. Window shows for 3 seconds (success message)
4. Window hides automatically

**Clock Out from Tray:**
1. Right-click tray icon
2. Click "Clock Out"
3. Uses last screenshot timestamp
4. Window shows for 5 seconds (confirmation)
5. Window hides automatically

### Menu State Logic
```
Not logged in:    Clock In disabled
Logged in, not clocked:  Clock In enabled, Clock Out disabled
Clocked in:       Clock In disabled, Clock Out enabled
On break:         Both enabled
```

---

## 📋 Complete Workflow Example

### Morning Startup
```
1. Turn on PC
2. Worker app starts (or you launch it)
3. Auto-login with saved credentials ✅
4. Auto clock-in after 2 seconds ✅
5. Screenshot capture starts ✅
6. Window hides to system tray
```

### During Work Day
```
- App runs quietly in system tray
- Screenshots captured every 5 minutes (compressed to ~200KB)
- Activity changes queued for batch flush
- Window hidden - not distracting
```

### Quick Check/Action
```
- Right-click tray icon
- See Clock Out option (enabled = you're working)
- Click if needed
- Window shows briefly, then hides
```

### End of Day
```
Option 1: Manual Clock Out
- Right-click tray → Clock Out
- Or open window → Click Out button

Option 2: Close Window
- Click X button
- Auto clock-out with last screenshot time

Option 3: App Crash
- Session ends automatically
- Uses last screenshot timestamp
- All activity logs flushed
```

---

## ⚙️ Configuration Options

### Environment Variables

```env
# Screenshot Settings
SCREENSHOT_INTERVAL=300          # Seconds between screenshots (default: 300 = 5 min)
MAX_SCREENSHOT_SIZE_KB=200       # Max screenshot size in KB (default: 200)

# Auto Check-In
AUTO_CHECK_IN=true               # Enable auto check-in on startup (default: true)

# Profile Refresh
WORKER_PROFILE_REFRESH_INTERVAL=900  # Seconds (default: 15 min)

# API Configuration
ADMIN_API_URL=http://localhost:5000  # Admin server URL

# Browser Extension
BROWSER_BRIDGE_PORT=8765         # Port for browser extension (default: 8765)
```

---

## 🔍 Troubleshooting

### System Tray Not Showing
**Problem:** No tray icon visible
**Solution:** 
- Install pystray: `pip install pystray`
- Check if Windows supports system tray
- Look in hidden icons area (click ^ arrow)

### Auto Check-In Not Working
**Problem:** App logs in but doesn't clock in
**Solution:**
- Check if already clocked in from previous session
- Check console logs for `[Auto Check-in]` messages
- Verify saved credentials exist

### Screenshot Too Large
**Problem:** Screenshots still > 200KB
**Solution:**
- Check `MAX_SCREENSHOT_SIZE_KB` environment variable
- Review compression settings in code
- Check console for size logs: `Size: XXX KB`

### Auto Checkout Not Triggering
**Problem:** Window closes but no checkout happens
**Solution:**
- Check if actually clocked in (session_id exists)
- Review console logs for `[Auto Checkout]` messages
- Verify API connection is working

---

## 📊 Performance Comparison

### Before These Features
```
- No tray: Window always visible, distracting
- Manual check-in: Must remember to clock in
- No auto checkout: Forgotten sessions on crash
- Large screenshots: ~2MB each, slow uploads
- Individual activity logs: 50+ API calls/day
```

### After These Features
```
✓ System tray: Hidden, professional
✓ Auto check-in: Never forget to clock in
✓ Auto checkout: Always ends properly
✓ Compressed screenshots: ~200KB (90% smaller)
✓ Batch activity logs: 1 API call/day
```

### Storage Savings Example (8-hour day, 5-min interval)
```
Before: 96 screenshots × 2MB = 192MB/day
After:  96 screenshots × 200KB = 19MB/day
Savings: 173MB per day, per worker!
```

---

## 🎓 Tips & Best Practices

### 1. **Use Saved Credentials**
- Check "Remember credentials" on login
- Enables auto-login and auto check-in
- Saves time every morning

### 2. **Keep App in System Tray**
- Hide window after clock-in
- Use tray menu for quick actions
- Less distracting during work

### 3. **Don't Worry About Closing Window**
- Auto checkout will handle it
- All activity will be saved
- Session will end properly

### 4. **Monitor Tray Icon**
- Clock In enabled = Not working yet
- Clock Out enabled = Currently working
- Both disabled = Not logged in or on break

### 5. **Check Console Logs**
- Look for `[Auto Check-in]` messages
- Verify screenshot sizes: `Size: XXX KB`
- Check batch flush: `[Batch Flush]` messages

---

## 📝 Summary

| Feature | Benefit | Status |
|---------|---------|--------|
| System Tray | Hidden, professional | ✅ Active |
| Auto Check-In | Never forget to clock in | ✅ Active |
| Auto Checkout | Always ends properly | ✅ Active |
| Screenshot Compression | 90% smaller files | ✅ Active |
| Batch Activity Logs | 98% fewer API calls | ✅ Active |
| Tray Clock Controls | Quick actions | ✅ Active |

All features work automatically once enabled. No manual configuration needed for standard use!

---

**Version:** 2.0.0  
**Last Updated:** April 2026  
**Platform:** Windows (full support), macOS/Linux (partial tray support)
