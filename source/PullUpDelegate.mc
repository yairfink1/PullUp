import Toybox.Attention;
import Toybox.FitContributor;
import Toybox.Lang;
import Toybox.Sensor;
import Toybox.System;
import Toybox.WatchUi;
import Toybox.ActivityRecording;
import Toybox.Activity;
import Toybox.SensorLogging;
import Toybox.Timer;

// ---------------------------------------------------------------------------
// PullUpDelegate - handles Single Quick Set mode and idle mode switching.
//
// Key Features:
//   - Quick standalone set recording with 100 Hz detection.
//   - FitContributor Session & Lap Developer Fields written on save.
//   - Scrolling DOWN when idle switches to Multi-Set Workout mode.
// ---------------------------------------------------------------------------
class PullUpDelegate extends WatchUi.BehaviorDelegate {

    private var _view           as PullUpView;
    private var _detector       as PullUpDetector;
    private var _isRecording    as Boolean = false;
    private var _uiTimer        as Timer.Timer?;
    private var _elapsedSeconds as Number = 0;
    private var _hapticPending  as Boolean = false;
    private var _sampleRate     as Number = 100;

    // Recording session & FIT fields.
    private var _session        as ActivityRecording.Session?;
    private var _sensorLogger   as SensorLogging.SensorLogger?;
    private var _totalRepsField as FitContributor.Field?;
    private var _lapRepsField   as FitContributor.Field?;

    function initialize(view as PullUpView) {
        BehaviorDelegate.initialize();
        _view     = view;
        _detector = new PullUpDetector();
    }

    // -- Physical Key Handling ----------------------------------------------

    function onKey(keyEvent as WatchUi.KeyEvent) as Boolean {
        var key = keyEvent.getKey();
        if (key == WatchUi.KEY_ENTER || key == WatchUi.KEY_START) {
            return onSelect();
        } else if (_isRecording && (key == WatchUi.KEY_DOWN || key == WatchUi.KEY_UP)) {
            // Block view switching while actively recording a set
            return true;
        }
        return BehaviorDelegate.onKey(keyEvent);
    }

    // SELECT / START - Toggle recording.
    function onSelect() as Boolean {
        if (_isRecording) {
            _stopRecording();
        } else {
            _startRecording();
        }
        return true;
    }

    // -- Periodic UI Timer --------------------------------------------------

    public function onUiTimer() as Void {
        if (!_isRecording) {
            return;
        }
        _elapsedSeconds++;
        _updateUi();
    }

    private function _updateUi() as Void {
        var reps = _detector.getRepCount();
        if (_lapRepsField != null) {
            _lapRepsField.setData(reps);
        }
        if (_totalRepsField != null) {
            _totalRepsField.setData(reps);
        }

        var minutes = _elapsedSeconds / 60;
        var seconds = _elapsedSeconds % 60;
        var timeStr = minutes.format("%02d") + ":" + seconds.format("%02d");

        if (_detector.isSetLocked()) {
            _view.setStatus("SET LOCKED");
        } else if (_detector.getState() == STATE_MOUNT_SETTLING) {
            _view.setStatus("SETTLING...");
        } else {
            _view.setStatus("RECORDING...");
        }

        _view.setRecording(_isRecording);
        _view.setRepCount(reps);
        _view.setElapsedTime(timeStr);
        _view.setSampleCount(_detector.getSampleCount());
        WatchUi.requestUpdate();
    }

    // -- Session control ----------------------------------------------------

    private function _startRecording() as Void {
        // Query best sample rate (target 100 Hz).
        _sampleRate = 100;
        if (Sensor has :getMaxSampleRate) {
            var maxRate = Sensor.getMaxSampleRate();
            if (maxRate != null && maxRate > 0) {
                _sampleRate = (maxRate >= 100) ? 100 : maxRate;
            }
        }

        _detector.start(_sampleRate);
        _elapsedSeconds = 0;
        _hapticPending  = false;
        _isRecording    = true;

        // Native 100 Hz accelerometer logging.
        _sensorLogger = new SensorLogging.SensorLogger(
            { :accelerometer => { :enabled => true } }
        );

        // FIT recording session.
        _session = ActivityRecording.createSession({
            :name         => "PullUp Quick Set",
            :sport        => Activity.SPORT_TRAINING,
            :subSport     => Activity.SUB_SPORT_STRENGTH_TRAINING,
            :sensorLogger => _sensorLogger
        });

        // Developer FIT fields — no :nativeNum to avoid conflicts with native
        // session/lap fields (e.g. nativeNum=7 collides with total_calories).
        // Data appears under "Connect IQ" in Garmin Connect.
        _totalRepsField = _session.createField("Total Reps", 0, FitContributor.DATA_TYPE_UINT16,
            { :mesgType => FitContributor.MESG_TYPE_SESSION, :units => "reps" });
        _lapRepsField   = _session.createField("Set Reps", 1, FitContributor.DATA_TYPE_UINT16,
            { :mesgType => FitContributor.MESG_TYPE_LAP, :units => "reps" });

        _lapRepsField.setData(0);
        _totalRepsField.setData(0);

        _session.start();

        // Register online sensor listener.
        var options = {
            :period        => 1,
            :accelerometer => { :enabled => true, :sampleRate => _sampleRate }
        };
        Sensor.registerSensorDataListener(method(:onSensorData), options);

        // Start decoupled UI timer.
        _uiTimer = new Timer.Timer();
        _uiTimer.start(method(:onUiTimer), 1000, true);

        _view.setStatus("RECORDING...");
        _updateUi();

        System.println("PullUpDelegate: Quick set recording started at " + _sampleRate + " Hz");
    }

    private function _stopRecording() as Void {
        _isRecording = false;

        if (_uiTimer != null) {
            _uiTimer.stop();
            _uiTimer = null;
        }

        Sensor.unregisterSensorDataListener();

        var detectedReps = _detector.getRepCount();
        if (_lapRepsField != null) {
            _lapRepsField.setData(detectedReps);
        }
        if (_totalRepsField != null) {
            _totalRepsField.setData(detectedReps);
        }

        // Keep _session open so that the lap message remains active until
        // the user confirms or adjusts the rep count on PullUpEditView.
        var sessionToPass = _session;
        _session      = null;
        _sensorLogger = null;

        System.println("PullUpDelegate: Quick set stopped - detected reps: " + detectedReps);

        // Push confirmation screen.
        var editView     = new PullUpEditView(detectedReps, false, 1);
        var editDelegate = new PullUpEditDelegate(editView, sessionToPass, null, false, 1);
        editDelegate.setFitFields(_totalRepsField, _lapRepsField);
        _totalRepsField = null;
        _lapRepsField   = null;

        WatchUi.pushView(editView, editDelegate, WatchUi.SLIDE_UP);
    }

    // -- Sensor callback ----------------------------------------------------

    public function onSensorData(sensorData as Sensor.SensorData) as Void {
        if (!_isRecording) {
            return;
        }

        try {
            var accelData = sensorData.accelerometerData;
            if (accelData == null) {
                return;
            }

            var xs = accelData.x;
            var ys = accelData.y;
            var zs = accelData.z;
            if (xs == null || ys == null || zs == null) {
                return;
            }

            var n = xs.size();
            if (ys.size() < n) { n = ys.size(); }
            if (zs.size() < n) { n = zs.size(); }

            var repChanged = false;
            for (var i = 0; i < n; i++) {
                if (xs[i] != null && ys[i] != null && zs[i] != null) {
                    var res = _detector.processSample(xs[i].toNumber(), ys[i].toNumber(), zs[i].toNumber());
                    if (res == 1) {
                        _hapticPending = true;
                        repChanged = true;
                    } else if (res == -1) {
                        repChanged = true;
                    }
                }
            }

            if (_hapticPending) {
                _hapticPending = false;
                _triggerHaptic();
            }

            if (repChanged || _detector.isSetLocked()) {
                _updateUi();
            }
        } catch (e) {
            System.println("PullUpDelegate onSensorData exception: " + e.getErrorMessage());
        }
    }

    private function _triggerHaptic() as Void {
        try {
            if (Attention has :vibrate) {
                var vibeData = [new Attention.VibeProfile(50, 150)] as Array<Attention.VibeProfile>;
                Attention.vibrate(vibeData);
            }
        } catch (e) {
            System.println("PullUpDelegate haptic error: " + e.getErrorMessage());
        }
    }
}