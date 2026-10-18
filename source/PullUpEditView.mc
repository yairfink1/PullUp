import Toybox.Graphics;
import Toybox.Lang;
import Toybox.WatchUi;

// ---------------------------------------------------------------------------
// PullUpEditView - post-set confirmation and rep adjustment screen.
// ---------------------------------------------------------------------------
class PullUpEditView extends WatchUi.View {

    private var _repCount   as Number;
    private var _isMultiSet as Boolean = false;
    private var _setNumber  as Number  = 1;

    function initialize(detectedReps as Number, isMultiSet as Boolean, setNumber as Number) {
        View.initialize();
        _repCount   = detectedReps;
        _isMultiSet = isMultiSet;
        _setNumber  = setNumber;
    }

    function onLayout(dc as Graphics.Dc) as Void {
        // Drawn dynamically in onUpdate.
    }

    function onUpdate(dc as Graphics.Dc) as Void {
        var w  = dc.getWidth();
        var h  = dc.getHeight();
        var cx = w / 2;
        var numFont = (h >= 360) ? Graphics.FONT_NUMBER_THAI_HOT : Graphics.FONT_NUMBER_HOT;

        // Background.
        dc.setColor(Graphics.COLOR_BLACK, Graphics.COLOR_BLACK);
        dc.clear();

        // 1. Title
        var titleText = _isMultiSet ? ("SET " + _setNumber + " COMPLETE") : "SET COMPLETE";
        dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, (h * 0.12).toNumber(), Graphics.FONT_SMALL, titleText, Graphics.TEXT_JUSTIFY_CENTER);

        // 2. Large editable rep count
        var isPr = (_repCount > PullUpStorage.getPrSet());
        var repColor = isPr ? Graphics.COLOR_YELLOW : Graphics.COLOR_ORANGE;
        dc.setColor(repColor, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, (h * 0.25).toNumber(), numFont, _repCount.toString(), Graphics.TEXT_JUSTIFY_CENTER);

        // 3. Hints
        dc.setColor(Graphics.COLOR_LT_GRAY, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, (h * 0.60).toNumber(), Graphics.FONT_XTINY, "UP / DOWN to adjust", Graphics.TEXT_JUSTIFY_CENTER);

        var actionHint = _isMultiSet ? "START = Save & Rest  |  BACK = Discard" : "START = Save   BACK = Discard";
        dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, (h * 0.72).toNumber(), Graphics.FONT_XTINY, actionHint, Graphics.TEXT_JUSTIFY_CENTER);

        if (isPr) {
            dc.setColor(Graphics.COLOR_YELLOW, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, (h * 0.83).toNumber(), Graphics.FONT_XTINY, "* NEW RECORD CANDIDATE *", Graphics.TEXT_JUSTIFY_CENTER);
        }
    }

    public function increment() as Void {
        _repCount++;
    }

    public function decrement() as Void {
        if (_repCount > 0) {
            _repCount--;
        }
    }

    public function getRepCount() as Number {
        return _repCount;
    }
}