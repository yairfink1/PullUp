import Toybox.FitContributor;
import Toybox.Lang;
import Toybox.System;
import Toybox.WatchUi;
import Toybox.ActivityRecording;

// ---------------------------------------------------------------------------
// PullUpEditDelegate - handles input on post-set confirmation screen.
//
// Supports both Single Quick Set and Multi-Set Workout modes, including
// holding UP (Menu) to reclassify between PULL UP and CHIN UP.
// ---------------------------------------------------------------------------
class PullUpEditDelegate extends WatchUi.BehaviorDelegate {

    private var _editView        as PullUpEditView;
    private var _session         as ActivityRecording.Session?;
    private var _multiDelegate   as PullUpMultiSetController?;
    private var _isMultiSet      as Boolean = false;
    private var _totalRepsField  as FitContributor.Field?;
    private var _lapRepsField    as FitContributor.Field?;
    private var _pullRepsField   as FitContributor.Field?;
    private var _chinRepsField   as FitContributor.Field?;
    private var _lapExField      as FitContributor.Field?;

    function initialize(
        editView        as PullUpEditView,
        session         as ActivityRecording.Session?,
        multiDelegate   as PullUpMultiSetController?,
        isMultiSet      as Boolean,
        setNumber       as Number
    ) {
        BehaviorDelegate.initialize();
        _editView      = editView;
        _session       = session;
        _multiDelegate = multiDelegate;
        _isMultiSet    = isMultiSet;
    }

    // Direct key event handler for physical watch buttons.
    function onKey(keyEvent as WatchUi.KeyEvent) as Boolean {
        var key = keyEvent.getKey();
        if (key == WatchUi.KEY_UP) {
            _editView.increment();
            WatchUi.requestUpdate();
            return true;
        } else if (key == WatchUi.KEY_DOWN) {
            _editView.decrement();
            WatchUi.requestUpdate();
            return true;
        } else if (key == WatchUi.KEY_MENU) {
            return onMenu();
        } else if (key == WatchUi.KEY_ENTER || key == WatchUi.KEY_START) {
            return onSelect();
        } else if (key == WatchUi.KEY_ESC) {
            return onBack();
        }
        return BehaviorDelegate.onKey(keyEvent);
    }

    // Behavioral UP.
    function onPreviousPage() as Boolean {
        _editView.increment();
        WatchUi.requestUpdate();
        return true;
    }

    // Behavioral DOWN.
    function onNextPage() as Boolean {
        _editView.decrement();
        WatchUi.requestUpdate();
        return true;
    }

    // Hold UP / Menu toggles exercise type: PULL UP <-> CHIN UP.
    function onMenu() as Boolean {
        _editView.toggleExerciseType();
        System.println("PullUpEditDelegate: Exercise toggled to " + _editView.getExerciseName());
        WatchUi.requestUpdate();
        return true;
    }

    // Set developer fields for single set mode.
    public function setFitFields(
        totalField as FitContributor.Field?,
        lapField   as FitContributor.Field?,
        pullField  as FitContributor.Field?,
        chinField  as FitContributor.Field?,
        lapExField as FitContributor.Field?
    ) as Void {
        _totalRepsField = totalField;
        _lapRepsField   = lapField;
        _pullRepsField  = pullField;
        _chinRepsField  = chinField;
        _lapExField     = lapExField;
    }

    // SELECT / START - Save set.
    function onSelect() as Boolean {
        var reps     = _editView.getRepCount();
        var isChinUp = _editView.isChinUp();

        if (_isMultiSet && _multiDelegate != null) {
            WatchUi.popView(WatchUi.SLIDE_DOWN);
            _multiDelegate.onSetConfirmedWithType(reps, isChinUp);
        } else {
            // Single Quick Set mode.
            // CRITICAL ORDER: write confirmed reps and exercise type to all fields BEFORE stop().
            if (_totalRepsField != null) {
                _totalRepsField.setData(reps);
            }
            if (_lapRepsField != null) {
                _lapRepsField.setData(reps);
            }
            if (_pullRepsField != null) {
                _pullRepsField.setData(isChinUp ? 0 : reps);
            }
            if (_chinRepsField != null) {
                _chinRepsField.setData(isChinUp ? reps : 0);
            }
            if (_lapExField != null) {
                _lapExField.setData(isChinUp ? 1 : 0);
            }

            System.println("PullUpEditDelegate: confirmed reps=" + reps + " (" + _editView.getExerciseName() + "), stopping session.");

            if (_session != null && _session.isRecording()) {
                _session.stop();
            }
            if (_session != null) {
                // Empty sets (0 reps) must not pollute Garmin Connect with blank activities.
                if (reps > 0) {
                    _session.save();
                    System.println("PullUpEditDelegate: FIT session saved.");
                } else {
                    _session.discard();
                    System.println("PullUpEditDelegate: 0 reps, FIT session discarded.");
                }
                _session = null;
            }

            var prResult = PullUpStorage.addRepsWithPrCheck(reps, true);
            WatchUi.popView(WatchUi.SLIDE_DOWN);

            if (prResult[:isPr] as Boolean) {
                var celebView = new PullUpCelebrationView(
                    prResult[:title] as String,
                    prResult[:value] as Number,
                    prResult[:sub] as String
                );
                var celebDelegate = new PullUpCelebrationDelegate(celebView);
                WatchUi.pushView(celebView, celebDelegate, WatchUi.SLIDE_UP);
            }
        }
        return true;
    }

    // BACK - Discard set.
    function onBack() as Boolean {
        if (_isMultiSet && _multiDelegate != null) {
            WatchUi.popView(WatchUi.SLIDE_DOWN);
            _multiDelegate.onSetDiscarded();
        } else {
            if (_session != null && _session.isRecording()) {
                _session.stop();
            }
            if (_session != null) {
                _session.discard();
                System.println("PullUpEditDelegate: FIT session discarded.");
                _session = null;
            }
            WatchUi.popView(WatchUi.SLIDE_DOWN);
        }
        return true;
    }
}
