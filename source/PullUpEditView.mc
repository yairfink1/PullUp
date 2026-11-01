import Toybox.Graphics;
import Toybox.Lang;
import Toybox.WatchUi;

// ---------------------------------------------------------------------------
// PullUpEditView - post-set confirmation, rep adjustment, and exercise toggle.
// ---------------------------------------------------------------------------
class PullUpEditView extends WatchUi.View {

    private var _repCount     as Number;
    private var _isMultiSet   as Boolean = false;
    private var _setNumber    as Number  = 1;
    private var _exerciseName as String  = "PULL UP";

    function initialize(detectedReps as Number, isMultiSet as Boolean, setNumber as Number, exerciseName as String or Null) {
        View.initialize();
        _repCount     = detectedReps;
        _isMultiSet   = isMultiSet;
        _setNumber    = setNumber;
        _exerciseName = (exerciseName != null) ? exerciseName : "PULL UP";
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

        // 1. Title with dynamic exercise name: "PULL UP DONE" or "CHIN UP DONE" / "SET 1: CHIN UP"
        var titleText = _isMultiSet
            ? ("SET " + _setNumber + ": " + _exerciseName)
            : (_exerciseName + " DONE");
        dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, (h * 0.12).toNumber(), Graphics.FONT_SMALL, titleText, Graphics.TEXT_JUSTIFY_CENTER);

        // 2. Large editable rep count
        var isPr = (_repCount > PullUpStorage.getPrSet());
        var repColor = isPr ? Graphics.COLOR_YELLOW : Graphics.COLOR_ORANGE;
        dc.setColor(repColor, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, (h * 0.23).toNumber(), numFont, _repCount.toString(), Graphics.TEXT_JUSTIFY_CENTER);

        // 3. Hints (bezel-safe stacked rows)
        dc.setColor(Graphics.COLOR_LT_GRAY, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, (h * 0.56).toNumber(), Graphics.FONT_XTINY, "UP / DOWN: Adjust Reps", Graphics.TEXT_JUSTIFY_CENTER);

        dc.setColor(Graphics.COLOR_BLUE, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, (h * 0.63).toNumber(), Graphics.FONT_XTINY, "Hold UP: Pull / Chin", Graphics.TEXT_JUSTIFY_CENTER);

        var saveHint = _isMultiSet ? "START: Save & Rest" : "START: Save";
        dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, (h * 0.71).toNumber(), Graphics.FONT_XTINY, saveHint, Graphics.TEXT_JUSTIFY_CENTER);

        dc.setColor(Graphics.COLOR_LT_GRAY, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, (h * 0.78).toNumber(), Graphics.FONT_XTINY, "BACK: Discard", Graphics.TEXT_JUSTIFY_CENTER);

        if (isPr) {
            dc.setColor(Graphics.COLOR_YELLOW, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, (h * 0.85).toNumber(), Graphics.FONT_XTINY, "* NEW RECORD *", Graphics.TEXT_JUSTIFY_CENTER);
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

    public function toggleExerciseType() as Void {
        if (_exerciseName.equals("CHIN UP")) {
            _exerciseName = "PULL UP";
        } else {
            _exerciseName = "CHIN UP";
        }
    }

    public function getRepCount() as Number {
        return _repCount;
    }

    public function getExerciseName() as String {
        return _exerciseName;
    }

    public function isChinUp() as Boolean {
        return _exerciseName.equals("CHIN UP");
    }
}
