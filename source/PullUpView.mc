import Toybox.Graphics;
import Toybox.Lang;
import Toybox.System;
import Toybox.Timer;
import Toybox.WatchUi;

// ---------------------------------------------------------------------------
// PullUpView - main live recording screen for Single Quick Set mode.
// ---------------------------------------------------------------------------
class PullUpView extends WatchUi.View {

    private var _statusText   as String  = "PULL UP";
    private var _repCount     as Number  = 0;
    private var _timeText     as String  = "00:00";
    private var _sampleText   as String  = "Press START";
    private var _isRecording  as Boolean = false;

    // Page indicator auto-hide (visible for 3 seconds after interaction).
    private var _lastInteractionTime as Number = 0;
    private var _indicatorTimer      as Timer.Timer?;

    function initialize() {
        View.initialize();
        _lastInteractionTime = System.getTimer();
    }

    function onLayout(dc as Graphics.Dc) as Void {
        // Drawn dynamically in onUpdate.
    }

    function onShow() as Void {
        resetIndicatorTimer();
        WatchUi.requestUpdate();
    }

    function onHide() as Void {
        if (_indicatorTimer != null) {
            _indicatorTimer.stop();
            _indicatorTimer = null;
        }
    }

    public function resetIndicatorTimer() as Void {
        _lastInteractionTime = System.getTimer();
        if (_indicatorTimer == null) {
            _indicatorTimer = new Timer.Timer();
        }
        _indicatorTimer.stop();
        _indicatorTimer.start(method(:onIndicatorTimeout), PageIndicator.TIMEOUT_MS, false);
    }

    public function onIndicatorTimeout() as Void {
        WatchUi.requestUpdate();
    }

    function onUpdate(dc as Graphics.Dc) as Void {
        var w  = dc.getWidth();
        var cx = w / 2;

        var h  = dc.getHeight();
        var numFont = (h >= 360) ? Graphics.FONT_NUMBER_THAI_HOT : Graphics.FONT_NUMBER_HOT;

        // Clear background (AMOLED black).
        dc.setColor(Graphics.COLOR_BLACK, Graphics.COLOR_BLACK);
        dc.clear();

        if (_isRecording) {
            // 1. Status banner (top)
            dc.setColor(Graphics.COLOR_LT_GRAY, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, (h * 0.11).toNumber(), Graphics.FONT_SMALL, _statusText, Graphics.TEXT_JUSTIFY_CENTER);

            // 2. Large prominent Rep Count (green during live set)
            dc.setColor(Graphics.COLOR_GREEN, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, (h * 0.23).toNumber(), numFont, _repCount.toString(), Graphics.TEXT_JUSTIFY_CENTER);

            // 3. "REPS" caption
            dc.setColor(Graphics.COLOR_LT_GRAY, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, (h * 0.57).toNumber(), Graphics.FONT_XTINY, "REPS", Graphics.TEXT_JUSTIFY_CENTER);

            // 4. Elapsed Time ("MM:SS")
            dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, (h * 0.65).toNumber(), Graphics.FONT_MEDIUM, _timeText, Graphics.TEXT_JUSTIFY_CENTER);

            // 5. Samples counter
            dc.setColor(Graphics.COLOR_DK_GRAY, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, (h * 0.81).toNumber(), Graphics.FONT_XTINY, _sampleText, Graphics.TEXT_JUSTIFY_CENTER);
        } else {
            // -- Idle State --
            // 1. App Title
            dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, (h * 0.11).toNumber(), Graphics.FONT_SMALL, "QUICK SET", Graphics.TEXT_JUSTIFY_CENTER);
            // 2. Rep count (white)
            dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, (h * 0.23).toNumber(), numFont, "0", Graphics.TEXT_JUSTIFY_CENTER);
            // 3. Caption
            dc.setColor(Graphics.COLOR_LT_GRAY, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, (h * 0.57).toNumber(), Graphics.FONT_XTINY, "Press START to record", Graphics.TEXT_JUSTIFY_CENTER);
            // 4. Today total
            var today = PullUpStorage.getTodayReps();
            var prSet = PullUpStorage.getPrSet();
            dc.setColor(Graphics.COLOR_GREEN, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, (h * 0.67).toNumber(), Graphics.FONT_TINY, "Today: " + today + " reps", Graphics.TEXT_JUSTIFY_CENTER);
            // 5. PR hint
            if (prSet > 0) {
                dc.setColor(Graphics.COLOR_YELLOW, Graphics.COLOR_TRANSPARENT);
                dc.drawText(cx, (h * 0.77).toNumber(), Graphics.FONT_XTINY, "PR Set: " + prSet + " reps", Graphics.TEXT_JUSTIFY_CENTER);
            }
            // 6. Mode switch hint
            dc.setColor(Graphics.COLOR_DK_GRAY, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, (h * 0.86).toNumber(), Graphics.FONT_XTINY, "DOWN = Multi-Set Workout", Graphics.TEXT_JUSTIFY_CENTER);
        }

        // Side page dots (Page 1 of 3) - visible for 3s after interaction
        if (PageIndicator.isVisible(_lastInteractionTime)) {
            PageIndicator.draw(dc, 0, 3);
        }
    }

    // -- Public setters -----------------------------------------------------

    public function setStatus(text as String) as Void {
        _statusText = text;
    }

    public function setRepCount(count as Number) as Void {
        _repCount = count;
    }

    public function setElapsedTime(timeStr as String) as Void {
        _timeText = timeStr;
    }

    public function setSampleCount(samples as Number) as Void {
        _sampleText = "Samples: " + samples.toString();
    }

    public function setSubText(text as String) as Void {
        _sampleText = text;
    }

    public function setRecording(recording as Boolean) as Void {
        _isRecording = recording;
    }
}