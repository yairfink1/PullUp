import Toybox.Graphics;
import Toybox.Lang;
import Toybox.WatchUi;

// ---------------------------------------------------------------------------
// PullUpFinishView - confirmation screen before saving the multi-set workout.
// ---------------------------------------------------------------------------
class PullUpFinishView extends WatchUi.View {

    private var _totalReps as Number;

    function initialize(totalReps as Number) {
        View.initialize();
        _totalReps = totalReps;
    }

    function onLayout(dc as Graphics.Dc) as Void {
        // Drawn dynamically in onUpdate.
    }

    function onUpdate(dc as Graphics.Dc) as Void {
        var w  = dc.getWidth();
        var h  = dc.getHeight();
        var cx = w / 2;
        var numFont = (h >= 360) ? Graphics.FONT_NUMBER_THAI_HOT : Graphics.FONT_NUMBER_HOT;

        // Clear background.
        dc.setColor(Graphics.COLOR_BLACK, Graphics.COLOR_BLACK);
        dc.clear();

        // 1. Title
        dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, (h * 0.11).toNumber(), Graphics.FONT_SMALL, "FINISH WORKOUT?", Graphics.TEXT_JUSTIFY_CENTER);

        // 2. Large Total Reps
        dc.setColor(Graphics.COLOR_GREEN, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, (h * 0.25).toNumber(), numFont, _totalReps.toString(), Graphics.TEXT_JUSTIFY_CENTER);

        // 3. Caption
        dc.setColor(Graphics.COLOR_LT_GRAY, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, (h * 0.59).toNumber(), Graphics.FONT_TINY, "TOTAL REPS COMPLETED", Graphics.TEXT_JUSTIFY_CENTER);

        // 4. Instructions
        dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, (h * 0.69).toNumber(), Graphics.FONT_XTINY, "START = Save & Exit", Graphics.TEXT_JUSTIFY_CENTER);

        dc.setColor(Graphics.COLOR_DK_GRAY, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, (h * 0.82).toNumber(), Graphics.FONT_XTINY, "DOWN = Resume Rest | BACK = Discard", Graphics.TEXT_JUSTIFY_CENTER);
    }
}
