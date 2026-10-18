import Toybox.Lang;
import Toybox.WatchUi;

// ---------------------------------------------------------------------------
// PullUpFinishDelegate - handles confirmation when completing a workout.
// ---------------------------------------------------------------------------
class PullUpFinishDelegate extends WatchUi.BehaviorDelegate {

    private var _multiDelegate as PullUpMultiSetController;
    private var _restDelegate  as PullUpRestDelegate;

    function initialize(multiDelegate as PullUpMultiSetController, restDelegate as PullUpRestDelegate) {
        BehaviorDelegate.initialize();
        _multiDelegate = multiDelegate;
        _restDelegate  = restDelegate;
    }

    function onKey(keyEvent as WatchUi.KeyEvent) as Boolean {
        var key = keyEvent.getKey();
        if (key == WatchUi.KEY_ENTER || key == WatchUi.KEY_START) {
            return onSelect();
        } else if (key == WatchUi.KEY_ESC) {
            return onBack();
        } else if (key == WatchUi.KEY_DOWN) {
            return onNextPage();
        }
        return BehaviorDelegate.onKey(keyEvent);
    }

    // START - Save workout and return to main screen.
    function onSelect() as Boolean {
        // Pop this finish screen and the underlying rest screen.
        WatchUi.popView(WatchUi.SLIDE_IMMEDIATE);
        WatchUi.popView(WatchUi.SLIDE_DOWN);
        _multiDelegate.finishWorkout();
        return true;
    }

    // BACK - Discard entire workout.
    function onBack() as Boolean {
        WatchUi.popView(WatchUi.SLIDE_IMMEDIATE);
        WatchUi.popView(WatchUi.SLIDE_DOWN);
        _multiDelegate.discardWorkout();
        return true;
    }

    // DOWN - Resume rest timer.
    function onNextPage() as Boolean {
        WatchUi.popView(WatchUi.SLIDE_DOWN);
        _restDelegate.resumeTimer();
        return true;
    }
}
