import Toybox.FitContributor;
import Toybox.Lang;
import Toybox.System;
import Toybox.WatchUi;
import Toybox.ActivityRecording;

// ---------------------------------------------------------------------------
// PullUpEditDelegate - handles input on post-set confirmation screen.
//
// Supports both Single Quick Set and Multi-Set Workout modes.
// ---------------------------------------------------------------------------
class PullUpEditDelegate extends WatchUi.BehaviorDelegate {

    private var _editView        as PullUpEditView;
    private var _session         as ActivityRecording.Session?;
    private var _multiDelegate   as PullUpMultiSetController?;
    private var _isMultiSet      as Boolean = false;
    private var _totalRepsField  as FitContributor.Field?;
    private var _lapRepsField    as FitContributor.Field?;

    // Constructor for Multi-Set Workout mode.
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

    // Set developer fields for single set mode.
    public function setFitFields(totalField as FitContributor.Field?, lapField as FitContributor.Field?) as Void {
        _totalRepsField = totalField;
        _lapRepsField   = lapField;
    }

    // SELECT / START - Save set.
    function onSelect() as Boolean {
        var reps = _editView.getRepCount();

        if (_isMultiSet && _multiDelegate != null) {
            WatchUi.popView(WatchUi.SLIDE_DOWN);
            _multiDelegate.onSetConfirmed(reps);
        } else {
            // Single Quick Set mode.
            // CRITICAL ORDER: write confirmed reps to both fields BEFORE stop().
            // Field descriptors must remain alive (non-null) through save() —
            // nulling them early causes the runtime to tear them down before
            // the FIT file is serialized, removing the fields from the record.
            if (_totalRepsField != null) {
                _totalRepsField.setData(reps);
            }
            if (_lapRepsField != null) {
                _lapRepsField.setData(reps);
            }

            System.println("PullUpEditDelegate: confirmed reps=" + reps + ", stopping session.");

            if (_session != null && _session.isRecording()) {
                _session.stop();
            }
            if (_session != null) {
                _session.save();
                System.println("PullUpEditDelegate: FIT session saved.");
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