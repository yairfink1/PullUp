import Toybox.Lang;
import Toybox.System;
import Toybox.Timer;
import Toybox.WatchUi;

// ---------------------------------------------------------------------------
// PullUpRestDelegate - handles user interaction during rest periods.
//
// Controls:
//   - START / onSelect : Start the next set immediately.
//   - BACK / onBack   : Finish or discard the workout.
// ---------------------------------------------------------------------------
class PullUpRestDelegate extends WatchUi.BehaviorDelegate {

    private var _view           as PullUpRestView;
    private var _multiDelegate  as PullUpMultiSetController;
    private var _timer          as Timer.Timer?;
    private var _restSeconds    as Number = 0;

    function initialize(view as PullUpRestView, multiDelegate as PullUpMultiSetController) {
        BehaviorDelegate.initialize();
        _view          = view;
        _multiDelegate = multiDelegate;

        _timer = new Timer.Timer();
        _timer.start(method(:onTimerTick), 1000, true);
    }

    public function onTimerTick() as Void {
        _restSeconds++;
        _view.setRestSeconds(_restSeconds);
        WatchUi.requestUpdate();
    }

    // Direct physical key handler.
    function onKey(keyEvent as WatchUi.KeyEvent) as Boolean {
        var key = keyEvent.getKey();
        if (key == WatchUi.KEY_ENTER || key == WatchUi.KEY_START) {
            return onSelect();
        } else if (key == WatchUi.KEY_ESC) {
            return onBack();
        }
        return BehaviorDelegate.onKey(keyEvent);
    }

    // START - Start next repetition set.
    function onSelect() as Boolean {
        _stopTimer();
        WatchUi.popView(WatchUi.SLIDE_DOWN);
        _multiDelegate.startNextSet();
        return true;
    }

    // BACK - Prompt to finish workout.
    function onBack() as Boolean {
        _stopTimer();
        // Show confirmation view to save or discard the workout.
        var finishView = new PullUpFinishView(_multiDelegate.getTotalReps());
        var finishDelegate = new PullUpFinishDelegate(_multiDelegate, self);
        WatchUi.pushView(finishView, finishDelegate, WatchUi.SLIDE_UP);
        return true;
    }

    public function resumeTimer() as Void {
        if (_timer == null) {
            _timer = new Timer.Timer();
            _timer.start(method(:onTimerTick), 1000, true);
        }
    }

    private function _stopTimer() as Void {
        if (_timer != null) {
            _timer.stop();
            _timer = null;
        }
    }
}
