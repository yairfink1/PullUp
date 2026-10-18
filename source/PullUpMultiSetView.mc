import Toybox.Graphics;
import Toybox.Lang;
import Toybox.System;
import Toybox.Timer;
import Toybox.WatchUi;

// ---------------------------------------------------------------------------
// PullUpMultiSetView - live recording + idle screen for Multi-Set Workout mode.
//
// Page 2 of 2. Displays current set number, per-set reps, total workout reps,
// elapsed time, and sensor sample count during active recording. In idle mode,
// shows a prompt to start the next set with today's totals.
// ---------------------------------------------------------------------------
class PullUpMultiSetView extends WatchUi.View {

    private var _isRecording  as Boolean = false;
    private var _currentSet   as Number  = 1;
    private var _setReps      as Number  = 0;
    private var _totalReps    as Number  = 0;
    private var _timeText     as String  = "00:00";
    private var _sampleText   as String  = "";

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
            // -- Active Recording Layout --

            // 1. Header: "SET X" with set number.
            dc.setColor(Graphics.COLOR_ORANGE, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, (h * 0.09).toNumber(), Graphics.FONT_SMALL, "SET " + _currentSet, Graphics.TEXT_JUSTIFY_CENTER);

            // 2. Large per-set Rep Count (green).
            dc.setColor(Graphics.COLOR_GREEN, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, (h * 0.22).toNumber(), numFont, _setReps.toString(), Graphics.TEXT_JUSTIFY_CENTER);

            // 3. "REPS" caption.
            dc.setColor(Graphics.COLOR_LT_GRAY, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, (h * 0.55).toNumber(), Graphics.FONT_XTINY, "REPS", Graphics.TEXT_JUSTIFY_CENTER);

            // 4. Elapsed set time.
            dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, (h * 0.62).toNumber(), Graphics.FONT_MEDIUM, _timeText, Graphics.TEXT_JUSTIFY_CENTER);

            // 5. Total workout reps so far.
            dc.setColor(Graphics.COLOR_DK_GRAY, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, (h * 0.78).toNumber(), Graphics.FONT_XTINY, "Total: " + _totalReps + " | " + _sampleText, Graphics.TEXT_JUSTIFY_CENTER);
        } else {
            // -- Idle State --

            // 1. Title
            dc.setColor(Graphics.COLOR_ORANGE, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, (h * 0.09).toNumber(), Graphics.FONT_SMALL, "MULTI-SET", Graphics.TEXT_JUSTIFY_CENTER);

            // 2. Set number indicator.
            dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, (h * 0.22).toNumber(), numFont, _currentSet.toString(), Graphics.TEXT_JUSTIFY_CENTER);

            // 3. "SET" caption.
            dc.setColor(Graphics.COLOR_LT_GRAY, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, (h * 0.55).toNumber(), Graphics.FONT_XTINY, "Ready for Set " + _currentSet, Graphics.TEXT_JUSTIFY_CENTER);

            // 4. Today total.
            var today = PullUpStorage.getTodayReps();
            dc.setColor(Graphics.COLOR_GREEN, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, (h * 0.67).toNumber(), Graphics.FONT_TINY, "Today: " + today + " reps", Graphics.TEXT_JUSTIFY_CENTER);

            // 5. Navigation hint.
            dc.setColor(Graphics.COLOR_DK_GRAY, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, (h * 0.86).toNumber(), Graphics.FONT_XTINY, "DOWN = 7-Day History", Graphics.TEXT_JUSTIFY_CENTER);
        }

        // Side page dots (Page 2 of 3) - visible for 3s after interaction.
        if (PageIndicator.isVisible(_lastInteractionTime)) {
            PageIndicator.draw(dc, 1, 3);
        }
    }

    // -- Public setters (called by PullUpMultiSetDelegate) -------------------

    public function setRecording(recording as Boolean) as Void {
        _isRecording = recording;
    }

    public function setCurrentSet(setNum as Number) as Void {
        _currentSet = setNum;
    }

    public function setSetReps(reps as Number) as Void {
        _setReps = reps;
    }

    public function setTotalReps(total as Number) as Void {
        _totalReps = total;
    }

    public function setElapsedTime(timeStr as String) as Void {
        _timeText = timeStr;
    }

    public function setSampleText(text as String) as Void {
        _sampleText = text;
    }
}
