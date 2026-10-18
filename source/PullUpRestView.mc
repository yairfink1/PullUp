import Toybox.Graphics;
import Toybox.Lang;
import Toybox.WatchUi;

// ---------------------------------------------------------------------------
// PullUpRestView - rest timer between sets in Multi-Set Workout mode.
// ---------------------------------------------------------------------------
class PullUpRestView extends WatchUi.View {

    private var _restSeconds  as Number = 0;
    private var _lastSetReps  as Number = 0;
    private var _totalReps    as Number = 0;
    private var _currentSet   as Number = 1;

    function initialize(lastSetReps as Number, totalReps as Number, nextSetNumber as Number) {
        View.initialize();
        _lastSetReps = lastSetReps;
        _totalReps   = totalReps;
        _currentSet  = nextSetNumber;
    }

    function onLayout(dc as Graphics.Dc) as Void {
        // Drawn dynamically in onUpdate.
    }

    public function setRestSeconds(seconds as Number) as Void {
        _restSeconds = seconds;
    }

    function onUpdate(dc as Graphics.Dc) as Void {
        var w  = dc.getWidth();
        var h  = dc.getHeight();
        var cx = w / 2;
        var numFont = (h >= 360) ? Graphics.FONT_NUMBER_THAI_HOT : Graphics.FONT_NUMBER_HOT;

        // Clear background.
        dc.setColor(Graphics.COLOR_BLACK, Graphics.COLOR_BLACK);
        dc.clear();

        // 1. Header: "REST"
        dc.setColor(Graphics.COLOR_BLUE, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, (h * 0.09).toNumber(), Graphics.FONT_SMALL, "REST", Graphics.TEXT_JUSTIFY_CENTER);

        // 2. Large Rest Timer (MM:SS)
        var m = _restSeconds / 60;
        var s = _restSeconds % 60;
        var timerStr = m.format("%02d") + ":" + s.format("%02d");
        dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, (h * 0.22).toNumber(), numFont, timerStr, Graphics.TEXT_JUSTIFY_CENTER);

        // 3. Last Set info
        dc.setColor(Graphics.COLOR_GREEN, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, (h * 0.55).toNumber(), Graphics.FONT_SMALL, "Last Set: " + _lastSetReps + " reps", Graphics.TEXT_JUSTIFY_CENTER);

        // 4. Total Workout Reps & Next Set Preview
        dc.setColor(Graphics.COLOR_LT_GRAY, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, (h * 0.65).toNumber(), Graphics.FONT_TINY, "Total: " + _totalReps + " reps (Next: Set " + _currentSet + ")", Graphics.TEXT_JUSTIFY_CENTER);

        // 5. Button Hints
        dc.setColor(Graphics.COLOR_DK_GRAY, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, (h * 0.82).toNumber(), Graphics.FONT_XTINY, "START = Start Set " + _currentSet + " | BACK = Finish", Graphics.TEXT_JUSTIFY_CENTER);
    }
}
