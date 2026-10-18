import Toybox.Lang;
import Toybox.WatchUi;

// ---------------------------------------------------------------------------
// PullUpMultiSetController
//
// Common base class / interface for multi-set workout controllers
// (implemented by PullUpMultiSetDelegate and PullUpContainerDelegate).
// ---------------------------------------------------------------------------
class PullUpMultiSetController extends WatchUi.BehaviorDelegate {

    function initialize() {
        BehaviorDelegate.initialize();
    }

    public function onSetConfirmed(reps as Number) as Void {
    }

    public function onSetDiscarded() as Void {
    }

    public function startNextSet() as Void {
    }

    public function finishWorkout() as Void {
    }

    public function discardWorkout() as Void {
    }

    public function getTotalReps() as Number {
        return 0;
    }
}
