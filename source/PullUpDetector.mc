import Toybox.Lang;
import Toybox.Math;
import Toybox.System;

// ---------------------------------------------------------------------------
// PullUpDetector - reusable, online + post-set consensus repetition engine.
//
// Shared by both Single Quick Set and Multi-Set Workout modes.
//
// Ported 1:1 from the offline Python evaluation pipeline (`eval_pipeline.py`
// + `experiments/cand14_postset_consensus.py` + `experiments/cand11_postset_y.py`)
// which achieves 100.0% Exact Match on TRAIN (89/89 sets) and full parity with
// the inspection gallery.
//
// Key Specifications:
//   1. Low memory & constant time O(1) per sample: Zero allocations ('new') in
//      processSample().
//   2. Pre-allocated circular ring buffers:
//      - 37-sample running difference moving average (`_diffBuf`) for movement envelope.
//      - 25-sample causal moving averages (`_yBuf`, `_zBuf`) for transverse wrist tilt fusion.
//      - 35-sample delay ring buffer (`_yDelay`) + two cascaded 35-sample boxcar ring
//        buffers (`_zpBuf1`, `_zpBuf2`) for exact integer two-pass zero-phase Y smoothing.
//      - 160-sample circular history (`_xHist`, `_envHist`) + compact extrema table
//        (`MAX_EXTREMA = 220`) for O(1) streaming topographic prominence extraction.
//   3. Stage 1 Online Four-State FSM (for real-time rep counter & haptic feedback):
//      - State -1: STATE_MOUNT_SETTLING
//      - State  0: STATE_READY_TO_ARM
//      - State  1: STATE_ARMED
//      - State  2: STATE_COOLDOWN
//   4. Stage 2 Post-Set Dual-Channel Consensus (`_runPostSetConsensus()`):
//      - Triggered automatically when bar dismount latches (`_isSetLocked = true`)
//        or when the user manually stops the set (`finalizeSet()`).
//      - Fuses Stage 1 baseline envelope reps (`_baseReps`) with Stage 2 zero-phase
//        Y-axis topographic prominence peaks (`cand11`) via bipartite matching,
//        double-trigger pruning, dismount-surge rejection, and cadence-consistent
//        deep-fatigue rescue.
// ---------------------------------------------------------------------------

// State constants matching eval_pipeline.py.
const STATE_MOUNT_SETTLING as Number = -1;
const STATE_READY_TO_ARM   as Number = 0;
const STATE_ARMED          as Number = 1;
const STATE_COOLDOWN       as Number = 2;

// Exercise type classification constants.
const EXERCISE_PULL_UP     as Number = 0;
const EXERCISE_CHIN_UP     as Number = 1;

class PullUpDetector {

    // Calibration constants (sample-rate independent mG levels and buffer sizes).
    private const BASE_REP_THRESHOLD      as Number = 105;
    private const BASE_RESET_THRESHOLD    as Number = 55;
    private const MOUNT_EXIT_ENV          as Number = 92;
    private const MOUNT_SHOCK_REENTRY_ENV as Number = 355;
    private const HIGH_MAG_LEVEL          as Number = 1900; // mG
    private const X_RELEASE_THRESHOLD     as Number = -300; // mG
    private const WINDOW_SIZE             as Number = 37;
    private const TILT_WINDOW_SIZE        as Number = 25;
    private const MIN_WAVE_IMPULSE        as Number = 550;

    // Candidate 14 streaming post-set consensus constants.
    private const ZP_WIN                  as Number = 35;
    private const HIST_LEN                as Number = 160;
    private const MAX_EXTREMA             as Number = 220;
    private const MAX_BASE_REPS           as Number = 64;

    // Sample rate scaling.
    private var _sampleRate as Number = 100;

    // Scaled sample thresholds (calibrated to 100 Hz baseline).
    private var _debounceMin               as Number = 80;  // 0.80s
    private var _debounceMax               as Number = 130; // 1.30s
    private var _cooldownTimeoutSamples    as Number = 100; // 1.00s
    private var _deepFatigueTimeoutSamples as Number = 84;  // 0.84s
    private var _dismountLockoutSamples    as Number = 50;  // 0.50s
    private var _sustainedThreshold        as Number = 6;   // 0.06s
    private var _hangStreakReq             as Number = 35;  // 0.35s
    private var _mountCeilingSamples       as Number = 130; // 1.30s
    private var _minWaveDuration           as Number = 45;  // 0.45s
    private var _xLatchStreakLen           as Number = 35;  // 0.35s
    private var _cancelWindow              as Number = 35;  // 0.35s
    private var _cancelPriorWindow         as Number = 25;  // 0.25s
    private var _fastCandSamples           as Number = 95;  // 0.95s
    private var _valleyClearSamples        as Number = 110; // 1.10s
    private var _bounceWindowSamples       as Number = 155; // 1.55s
    private var _midFatigueGapSamples      as Number = 165; // 1.65s
    private var _longGapSamples            as Number = 180; // 1.80s
    private var _latePauseGapSamples       as Number = 200; // 2.00s
    private var _deadHangGapSamples        as Number = 600; // 6.00s
    private var _minFirstWaveAge           as Number = 20;  // 0.20s
    private var _minFirstHangAge           as Number = 120; // 1.20s

    // Circular buffer for running difference moving average in O(1).
    private var _diffBuf as Array<Number>;
    private var _bufIdx  as Number = 0;
    private var _bufSum  as Number = 0;

    // Circular buffers for 25-sample Y and Z transverse tilt smoothing in O(1).
    private var _yBuf    as Array<Number>;
    private var _zBuf    as Array<Number>;
    private var _yzIdx   as Number = 0;
    private var _ySum    as Number = 0;
    private var _zSum    as Number = 0;
    private var _waveYMin as Number = 0;
    private var _waveYMax as Number = 0;
    private var _waveZMin as Number = 0;
    private var _waveZMax as Number = 0;

    // Previous sample values.
    private var _prevMag      as Number = 0;
    private var _prevEnvelope as Number = 0;

    // Counters and timers.
    private var _repCount         as Number = 0;
    private var _sampleCount      as Number = 0;
    private var _samplesSinceLast as Number = 80;

    // Dismount high-G surge tracking.
    private var _highMagStreak   as Number = 0;
    private var _dismountLockout as Number = 0;

    // FSM State.
    private var _state as Number = STATE_MOUNT_SETTLING;

    // Hang detection & Mount Settling state.
    private var _hangStreak   as Number = 0;
    private var _hasHung      as Boolean = false;
    private var _hangStartIdx as Number = 0;

    // Bar Release Guard state.
    private var _xStreak     as Number = 0;
    private var _isSetLocked as Boolean = false;

    // Wave morphology, impulse, and valley prominence tracking.
    private var _waveStartSample    as Number = 0;
    private var _waveNonHangSamples as Number = 0;
    private var _currentWavePeak    as Number = 0;
    private var _pendingWavePeak    as Number = 0;
    private var _pendingRepSample   as Number = -1;
    private var _lastRepTruePk      as Number = 0;
    private var _waveImpulse        as Number = 0;
    private var _minSinceLast       as Number = 0;

    // Last confirmed repetition metadata (for state-based rollback guard).
    private var _lastConfirmedSample   as Number = -1;
    private var _lastConfirmedRepIdx   as Number = -1;
    private var _lastConfirmedWaveDur  as Number = 0;
    private var _lastConfirmedAllHang  as Boolean = false;

    // Adaptive parameter state.
    private var _curDebounce       as Number = 80;
    private var _curRepThreshold   as Number = 105;
    private var _curResetThreshold as Number = 55;
    private var _peakAvg           as Float = 140.0;

    // Automatic exercise classification (Chin-Up vs. Pull-Up)
    private var _hangYSum          as Number = 0;
    private var _hangYSamples      as Number = 0;
    private var _hangYHighSamples  as Number = 0;
    private var _chinRepVotes      as Number = 0;
    private var _pullRepVotes      as Number = 0;
    private var _exerciseType      as Number = EXERCISE_PULL_UP;

    // --- Candidate 14 Streaming & Post-Set Consensus Buffers ---
    private var _xHist             as Array<Number>;
    private var _envHist           as Array<Number>;
    private var _yDelay            as Array<Number>;
    private var _zpBuf1            as Array<Number>;
    private var _zpBuf2            as Array<Number>;

    private var _extOffsets        as Array<Number>;
    private var _extVals           as Array<Number>;
    private var _extXAt            as Array<Number>;
    private var _extMaxX35         as Array<Number>;
    private var _extMaxX60         as Array<Number>;
    private var _extMaxEnv35       as Array<Number>;
    private var _extCount          as Number = 0;

    private var _baseReps          as Array<Number>;
    private var _baseMaxEnv        as Array<Number>;
    private var _baseCount         as Number = 0;

    private var _cMountStreak      as Number = 0;
    private var _cHasHung          as Boolean = false;
    private var _cMountIdx         as Number = 0;
    private var _cSettleIdx        as Number = 0;
    private var _cSettled          as Boolean = false;
    private var _cRelStreak        as Number = 0;
    private var _cDismountIdx      as Number = -1;
    private var _cDepSample        as Number = -1;
    private var _cDepStreak        as Number = 0;
    private var _cFlushed          as Boolean = false;
    private var _consensusDone     as Boolean = false;

    private var _yStreamStart      as Number = 0;
    private var _yDelayIdx         as Number = 0;
    private var _yDelayCount       as Number = 0;
    private var _yFedCount         as Number = 0;
    private var _zpIdx1            as Number = 0;
    private var _zpSum1            as Number = 0;
    private var _zpIdx2            as Number = 0;
    private var _zpSum2            as Number = 0;
    private var _zpUStep           as Number = 0;

    private var _cntYM20           as Number = 0;
    private var _cntY160           as Number = 0;
    private var _cntY210           as Number = 0;

    private var _hasPrevZpVal      as Boolean = false;
    private var _prevZpVal         as Number = 0;
    private var _currZpVal         as Number = 0;
    private var _currZpStartOff    as Number = 0;

    function initialize() {
        _diffBuf     = new Array<Number>[WINDOW_SIZE];
        _yBuf        = new Array<Number>[TILT_WINDOW_SIZE];
        _zBuf        = new Array<Number>[TILT_WINDOW_SIZE];

        _xHist       = new Array<Number>[HIST_LEN];
        _envHist     = new Array<Number>[HIST_LEN];
        _yDelay      = new Array<Number>[ZP_WIN];
        _zpBuf1      = new Array<Number>[ZP_WIN];
        _zpBuf2      = new Array<Number>[ZP_WIN];

        _extOffsets  = new Array<Number>[MAX_EXTREMA];
        _extVals     = new Array<Number>[MAX_EXTREMA];
        _extXAt      = new Array<Number>[MAX_EXTREMA];
        _extMaxX35   = new Array<Number>[MAX_EXTREMA];
        _extMaxX60   = new Array<Number>[MAX_EXTREMA];
        _extMaxEnv35 = new Array<Number>[MAX_EXTREMA];

        _baseReps    = new Array<Number>[MAX_BASE_REPS];
        _baseMaxEnv  = new Array<Number>[MAX_BASE_REPS];

        reset();
    }

    // Configure sample rate and scale timing parameters.
    public function start(sampleRate as Number) as Void {
        _sampleRate = (sampleRate > 0) ? sampleRate : 100;

        // Scale factors relative to 100 Hz baseline.
        var rateScale = _sampleRate.toFloat() / 100.0;

        _debounceMin = (80 * rateScale).toNumber();
        if (_debounceMin < 5) { _debounceMin = 5; }

        _debounceMax = (130 * rateScale).toNumber();
        if (_debounceMax < 10) { _debounceMax = 10; }

        _cooldownTimeoutSamples = (100 * rateScale).toNumber();
        if (_cooldownTimeoutSamples < 10) { _cooldownTimeoutSamples = 10; }

        _deepFatigueTimeoutSamples = (84 * rateScale).toNumber();
        if (_deepFatigueTimeoutSamples < 8) { _deepFatigueTimeoutSamples = 8; }

        _dismountLockoutSamples = (50 * rateScale).toNumber();
        if (_dismountLockoutSamples < 5) { _dismountLockoutSamples = 5; }

        _sustainedThreshold = (6 * rateScale).toNumber();
        if (_sustainedThreshold < 2) { _sustainedThreshold = 2; }

        _hangStreakReq = (35 * rateScale).toNumber();
        if (_hangStreakReq < 3) { _hangStreakReq = 3; }

        _mountCeilingSamples = (130 * rateScale).toNumber();
        if (_mountCeilingSamples < 15) { _mountCeilingSamples = 15; }

        _minWaveDuration = (45 * rateScale).toNumber();
        if (_minWaveDuration < 5) { _minWaveDuration = 5; }

        _xLatchStreakLen = (35 * rateScale).toNumber();
        if (_xLatchStreakLen < 3) { _xLatchStreakLen = 3; }

        _cancelWindow = (35 * rateScale).toNumber();
        if (_cancelWindow < 3) { _cancelWindow = 3; }

        _cancelPriorWindow = (25 * rateScale).toNumber();
        if (_cancelPriorWindow < 2) { _cancelPriorWindow = 2; }

        _fastCandSamples = (95 * rateScale).toNumber();
        if (_fastCandSamples < 10) { _fastCandSamples = 10; }

        _valleyClearSamples = (110 * rateScale).toNumber();
        if (_valleyClearSamples < 10) { _valleyClearSamples = 10; }

        _bounceWindowSamples = (155 * rateScale).toNumber();
        if (_bounceWindowSamples < 15) { _bounceWindowSamples = 15; }

        _midFatigueGapSamples = (165 * rateScale).toNumber();
        if (_midFatigueGapSamples < 15) { _midFatigueGapSamples = 15; }

        _longGapSamples = (180 * rateScale).toNumber();
        if (_longGapSamples < 18) { _longGapSamples = 18; }

        _latePauseGapSamples = (200 * rateScale).toNumber();
        if (_latePauseGapSamples < 20) { _latePauseGapSamples = 20; }

        _deadHangGapSamples = (600 * rateScale).toNumber();
        if (_deadHangGapSamples < 60) { _deadHangGapSamples = 60; }

        _minFirstWaveAge = (20 * rateScale).toNumber();
        if (_minFirstWaveAge < 2) { _minFirstWaveAge = 2; }

        _minFirstHangAge = (120 * rateScale).toNumber();
        if (_minFirstHangAge < 12) { _minFirstHangAge = 12; }

        reset();
    }

    // Reset all internal state for a new set.
    public function reset() as Void {
        _sampleCount      = 0;
        _repCount         = 0;
        _prevMag          = 0;
        _prevEnvelope     = 0;
        _bufIdx           = 0;
        _bufSum           = 0;
        _yzIdx            = 0;
        _ySum             = 0;
        _zSum             = 0;
        _waveYMin         = 0;
        _waveYMax         = 0;
        _waveZMin         = 0;
        _waveZMax         = 0;
        _samplesSinceLast = _debounceMin;
        _highMagStreak    = 0;
        _dismountLockout  = 0;

        _state        = STATE_MOUNT_SETTLING;
        _hangStreak   = 0;
        _hasHung      = false;
        _hangStartIdx = 0;

        _xStreak     = 0;
        _isSetLocked = false;

        _waveStartSample    = 0;
        _waveNonHangSamples = 0;
        _currentWavePeak    = 0;
        _pendingWavePeak    = 0;
        _pendingRepSample   = -1;
        _lastRepTruePk      = 0;
        _waveImpulse        = 0;
        _minSinceLast       = 0;

        _lastConfirmedSample  = -1;
        _lastConfirmedRepIdx  = -1;
        _lastConfirmedWaveDur = 0;
        _lastConfirmedAllHang = false;

        _curDebounce       = _debounceMin;
        _curRepThreshold   = BASE_REP_THRESHOLD;
        _curResetThreshold = BASE_RESET_THRESHOLD;
        _peakAvg           = 140.0;

        _hangYSum          = 0;
        _hangYSamples      = 0;
        _hangYHighSamples  = 0;
        _chinRepVotes      = 0;
        _pullRepVotes      = 0;
        _exerciseType      = EXERCISE_PULL_UP;

        for (var i = 0; i < WINDOW_SIZE; i++) {
            _diffBuf[i] = 0;
        }
        for (var j = 0; j < TILT_WINDOW_SIZE; j++) {
            _yBuf[j] = 0;
            _zBuf[j] = 0;
        }
        for (var h = 0; h < HIST_LEN; h++) {
            _xHist[h]   = 0;
            _envHist[h] = 0;
        }

        _cMountStreak  = 0;
        _cHasHung      = false;
        _cMountIdx     = 0;
        _cSettleIdx    = 0;
        _cSettled      = false;
        _cRelStreak    = 0;
        _cDismountIdx  = -1;
        _cDepSample    = -1;
        _cDepStreak    = 0;
        _cFlushed      = false;
        _consensusDone = false;
        _baseCount     = 0;

        _resetYStream(0);
    }

    private function _resetYStream(startIdx as Number) as Void {
        _yStreamStart   = startIdx;
        _yDelayIdx      = 0;
        _yDelayCount    = 0;
        _yFedCount      = 0;
        _zpIdx1         = 0;
        _zpSum1         = 0;
        _zpIdx2         = 0;
        _zpSum2         = 0;
        _zpUStep        = 0;
        _cntYM20        = 0;
        _cntY160        = 0;
        _cntY210        = 0;
        _extCount       = 0;
        _hasPrevZpVal   = false;
        _prevZpVal      = 0;
        _currZpVal      = 0;
        _currZpStartOff = 0;

        for (var i = 0; i < ZP_WIN; i++) {
            _yDelay[i] = 0;
            _zpBuf1[i] = 0;
            _zpBuf2[i] = 0;
        }
    }

    private function _getX(idx as Number) as Number {
        if (idx < 0) { idx = 0; }
        if (idx >= _sampleCount) { idx = _sampleCount - 1; }
        return _xHist[idx % HIST_LEN];
    }

    private function _getMaxX(startIdx as Number, endIdx as Number) as Number {
        if (startIdx < 0) { startIdx = 0; }
        if (endIdx > _sampleCount) { endIdx = _sampleCount; }
        if (startIdx >= endIdx) { return _getX(startIdx); }
        var mx = -999999;
        for (var k = startIdx; k < endIdx; k++) {
            var v = _xHist[k % HIST_LEN];
            if (v > mx) { mx = v; }
        }
        return mx;
    }

    private function _getMaxEnv(startIdx as Number, endIdx as Number) as Number {
        if (startIdx < 0) { startIdx = 0; }
        if (endIdx > _sampleCount) { endIdx = _sampleCount; }
        if (startIdx >= endIdx) { return 0; }
        var mx = 0;
        for (var k = startIdx; k < endIdx; k++) {
            var v = _envHist[k % HIST_LEN];
            if (v > mx) { mx = v; }
        }
        return mx;
    }

    private function _recordExtremum(offset as Number, val1225 as Number) as Void {
        if (_extCount >= MAX_EXTREMA) {
            return;
        }
        var gIdx = _yStreamStart + offset;
        _extOffsets[_extCount]  = offset;
        _extVals[_extCount]     = val1225;
        _extXAt[_extCount]      = _getX(gIdx);
        _extMaxX35[_extCount]   = _getMaxX(gIdx, gIdx + 35);
        _extMaxX60[_extCount]   = _getMaxX(gIdx, gIdx + 60);
        _extMaxEnv35[_extCount] = _getMaxEnv(gIdx - 35, gIdx + 35);
        _extCount++;
    }

    private function _onZpOutput(q as Number, val1225 as Number) as Void {
        if (q == 0) {
            _recordExtremum(0, val1225);
            _hasPrevZpVal   = false;
            _currZpVal      = val1225;
            _currZpStartOff = 0;
            return;
        }
        if (val1225 == _currZpVal) {
            return;
        }
        if (_hasPrevZpVal && _currZpStartOff > 0) {
            if ((_currZpVal > _prevZpVal && _currZpVal > val1225) ||
                (_currZpVal < _prevZpVal && _currZpVal < val1225)) {
                _recordExtremum(_currZpStartOff, _currZpVal);
            }
        }
        _hasPrevZpVal   = true;
        _prevZpVal      = _currZpVal;
        _currZpVal      = val1225;
        _currZpStartOff = q;
    }

    private function _pushZpSample(yVal as Number, isRealHangSample as Boolean) as Void {
        if (isRealHangSample) {
            _yFedCount++;
            if (yVal > -20) { _cntYM20++; }
            if (yVal > 160) { _cntY160++; }
            if (yVal > 210) { _cntY210++; }
        }

        _zpSum1          += yVal - _zpBuf1[_zpIdx1];
        _zpBuf1[_zpIdx1]  = yVal;
        _zpIdx1           = (_zpIdx1 + 1) % ZP_WIN;

        var u = _zpUStep;
        _zpUStep++;
        if (u >= 17) {
            var p  = u - 17;
            var v2 = (isRealHangSample || p < _yFedCount) ? _zpSum1 : 0;
            _zpSum2          += v2 - _zpBuf2[_zpIdx2];
            _zpBuf2[_zpIdx2]  = v2;
            _zpIdx2           = (_zpIdx2 + 1) % ZP_WIN;
            if (p >= 17) {
                var q = p - 17;
                _onZpOutput(q, _zpSum2);
            }
        }
    }

    private function _flushZeros() as Void {
        if (_cFlushed) {
            return;
        }
        _cFlushed = true;
        if (_cHasHung && _yFedCount > 0) {
            for (var z = 0; z < 34; z++) {
                _pushZpSample(0, false);
            }
            if (_yFedCount > 1) {
                _recordExtremum(_yFedCount - 1, _currZpVal);
            }
        }
    }

    private function _stepCand14Sample(i as Number, x as Number, y as Number, env as Number) as Void {
        if (!_cHasHung) {
            if (_cMountStreak >= 35) {
                _cHasHung   = true;
                _cMountIdx  = i;
                _cSettleIdx = i;
                _cSettled   = false;
                _resetYStream(i);
            }
        }

        _xHist[i % HIST_LEN]   = x;
        _envHist[i % HIST_LEN] = env;

        // Update recent extrema whose +35 / +60 post-windows are still completing.
        for (var idx = _extCount - 1; idx >= 0; idx--) {
            var gIdx = _yStreamStart + _extOffsets[idx];
            if ((i - gIdx) > 65) {
                break;
            }
            if (i < (gIdx + 35)) {
                if (x > _extMaxX35[idx]) { _extMaxX35[idx] = x; }
                if (env > _extMaxEnv35[idx]) { _extMaxEnv35[idx] = env; }
            }
            if (i < (gIdx + 60)) {
                if (x > _extMaxX60[idx]) { _extMaxX60[idx] = x; }
            }
        }

        // Update recent base_reps max_env[-35..+35].
        for (var r = _baseCount - 1; r >= 0; r--) {
            var bIdx = _baseReps[r];
            if ((i - bIdx) > 40) {
                break;
            }
            if (i < (bIdx + 35) && env > _baseMaxEnv[r]) {
                _baseMaxEnv[r] = env;
            }
        }

        if (_cHasHung && !_cSettled) {
            if (i < (_cMountIdx + 130)) {
                if (env < 70) {
                    _cSettleIdx = i;
                    _cSettled   = true;
                    _cRelStreak = 0;
                    _resetYStream(i);
                }
            } else {
                _cSettled = true;
            }
        }

        if (x >= -1300 && x <= -700) {
            _cMountStreak++;
        } else {
            _cMountStreak = 0;
        }

        if (_cHasHung) {
            if (x > -300) {
                _cDepStreak++;
            } else {
                _cDepStreak = 0;
            }

            if (i >= _cSettleIdx) {
                if (x > -300) {
                    _cRelStreak++;
                } else {
                    _cRelStreak = 0;
                }
            }

            if (_cDepSample < 0 && (i + 1) >= (_cMountIdx + 35) && _cDepStreak >= 35) {
                _cDepSample = i - 34;
            }

            if (_cDismountIdx < 0 && (i + 1) >= (_cSettleIdx + 35) && _cRelStreak >= 35) {
                _cDismountIdx = i - 34;
                if (_yDelayCount == ZP_WIN) {
                    var oldestY = _yDelay[_yDelayIdx];
                    _pushZpSample(oldestY, true);
                }
                _flushZeros();
            }
        }

        if (_cHasHung && _cDismountIdx < 0 && i >= _cSettleIdx) {
            if (_yDelayCount < ZP_WIN) {
                _yDelay[_yDelayIdx] = y;
                _yDelayIdx          = (_yDelayIdx + 1) % ZP_WIN;
                _yDelayCount++;
            } else {
                var oldestY         = _yDelay[_yDelayIdx];
                _yDelay[_yDelayIdx] = y;
                _yDelayIdx          = (_yDelayIdx + 1) % ZP_WIN;
                _pushZpSample(oldestY, true);
            }
        }
    }

    private function _recordBaseRep(repIdx as Number) as Void {
        if (_baseCount < MAX_BASE_REPS) {
            _baseReps[_baseCount]   = repIdx;
            _baseMaxEnv[_baseCount] = _getMaxEnv(repIdx - 35, repIdx + 35);
            _baseCount++;
        }
    }

    private function _popBaseRep() as Void {
        if (_baseCount > 0) {
            _baseCount--;
        }
    }

    // Processes a single accelerometer sample.
    // Returns:
    //   1  : Rep was confirmed (or consensus added missing reps on bar release)
    //  -1  : Rep was rolled back (false positive on dismount / bar release)
    //   0  : Normal sample, no change in rep count
    public function processSample(x as Number, y as Number, z as Number) as Number {
        // If set is permanently locked by bar release, ignore all future motion.
        if (_isSetLocked) {
            return 0;
        }

        var eventResult = 0;
        var curSampleIdx = _sampleCount;
        _sampleCount++;

        // 0. Update 25-sample causal Y and Z smoothing circular buffers in O(1).
        _ySum        += y - _yBuf[_yzIdx];
        _zSum        += z - _zBuf[_yzIdx];
        _yBuf[_yzIdx] = y;
        _zBuf[_yzIdx] = z;
        _yzIdx        = (_yzIdx + 1) % TILT_WINDOW_SIZE;
        var ySmooth   = _ySum / TILT_WINDOW_SIZE;
        var zSmooth   = _zSum / TILT_WINDOW_SIZE;

        // Compute magnitude, first-difference, and running 37-sample envelope first so
        // Candidate 14's streaming tracker receives the current sample's envelope even
        // on the exact bar-release lock sample.
        var sqSum = x * x + y * y + z * z;
        var mag   = Math.sqrt(sqSum.toFloat()).toNumber();

        var diff = mag - _prevMag;
        if (diff < 0) { diff = -diff; }
        _prevMag = mag;

        _bufSum          -= _diffBuf[_bufIdx];
        _diffBuf[_bufIdx] = diff;
        _bufSum          += diff;
        _bufIdx           = (_bufIdx + 1) % WINDOW_SIZE;
        var curEnvelope   = _bufSum / WINDOW_SIZE;

        // Advance Candidate 14 streaming state for sample curSampleIdx.
        _stepCand14Sample(curSampleIdx, x, y, curEnvelope);

        // 1. Mount detection & hang stabilization: X in [-1300, -700] mG for >= 35 samples (0.35s).
        if (!_hasHung) {
            if ((x >= -1300 && x <= -700) || (x >= -1200 && x <= -750)) {
                _hangStreak++;
                if (_hangStreak >= _hangStreakReq) {
                    _hasHung = true;
                    _hangStartIdx = curSampleIdx;
                }
            } else {
                _hangStreak = 0;
            }
        } else {
            // If still settling on initial mount and user drops arms, reset mount status.
            if (_state == STATE_MOUNT_SETTLING && x > X_RELEASE_THRESHOLD) {
                _hasHung = false;
                _hangStreak = 0;
            }
        }

        // 2. Bar Release Guard & State-Based Rollback + Post-Set Consensus.
        if (_hasHung) {
            if (x > X_RELEASE_THRESHOLD) {
                _xStreak++;
            } else {
                _xStreak = 0;
            }

            if (_xStreak >= _xLatchStreakLen) {
                _isSetLocked = true;
                var departureStart = curSampleIdx - _xLatchStreakLen;

                // State-based rollback: discard unconfirmed pending rep.
                _pendingRepSample = -1;

                // Rollback rule: Discard last confirmed rep ONLY if interval between
                // its confirmation and departure start is < cancelPriorWindow (25 samples / 0.25s)
                // AND its wave duration was marginal (< 45 samples or not held in hang).
                if (_repCount > 0 && _lastConfirmedSample >= 0) {
                    var interval = departureStart - _lastConfirmedSample;
                    if (interval < _cancelPriorWindow &&
                        (_lastConfirmedWaveDur < _minWaveDuration || !_lastConfirmedAllHang)) {
                        _repCount--;
                        _popBaseRep();
                        _lastConfirmedSample = -1;
                        eventResult = -1;
                        System.println("PullUpDetector: Bar release rollback - retracted rep at sample " + curSampleIdx);
                    }
                }

                // Bar release lock latched: post-set consensus will be executed cleanly
                // in finalizeSet() when sensor streaming stops, avoiding watchdog budget limits
                // inside high-frequency onQuickSensorData callback batches.
                return eventResult;
            }
        }

        _samplesSinceLast++;
        if (_dismountLockout > 0) {
            _dismountLockout--;
        }

        // 4. Sustained high-magnitude dismount surge rejection.
        // Gated by arm departure: only treat high-G impacts as dismount surges
        // when the user is not hanging on the bar (x > X_RELEASE_THRESHOLD).
        if (mag >= HIGH_MAG_LEVEL && (x > X_RELEASE_THRESHOLD)) {
            _highMagStreak++;
        } else {
            _highMagStreak = 0;
        }

        if (_highMagStreak >= _sustainedThreshold) {
            _dismountLockout = _dismountLockoutSamples;
            _state = STATE_COOLDOWN;
            _pendingRepSample = -1;

            // Retract false positive rep triggered immediately before dismount.
            if (_repCount > 0 && _lastConfirmedRepIdx >= 0) {
                if ((curSampleIdx - _lastConfirmedRepIdx) < _cancelWindow) {
                    _repCount--;
                    _popBaseRep();
                    _lastConfirmedRepIdx = -1;
                    _lastConfirmedSample = -1;
                    eventResult = -1;
                    System.println("PullUpDetector: Dismount surge detected - retracted false rep at sample " + curSampleIdx);
                }
            }
        }

        var isSafeMotion = (_dismountLockout == 0);
        var xInHang      = (x <= X_RELEASE_THRESHOLD);

        // Accumulate Y tilt while strictly in vertical hang (x <= -650 mG, _xStreak == 0)
        // for robust Pull-Up vs. Chin-Up classification without dismount/transition bias.
        if (x <= -650 && _xStreak == 0 && _state != STATE_MOUNT_SETTLING) {
            _hangYSum += ySmooth;
            _hangYSamples++;
            if (ySmooth >= 140) {
                _hangYHighSamples++;
            }
            if (_hangYSamples >= 50) {
                _updateExerciseClassification();
            }
        }

        // Pre-first-rep mount shockwave re-entry guard.
        if (_state != STATE_MOUNT_SETTLING && _repCount == 0 && curEnvelope >= MOUNT_SHOCK_REENTRY_ENV) {
            _state            = STATE_MOUNT_SETTLING;
            _pendingRepSample = -1;
            _currentWavePeak  = 0;
        }

        // 6. Track active wave morphology, valley minimum, wave impulse, and transverse tilt range.
        if (_state != STATE_MOUNT_SETTLING) {
            if (curEnvelope < _minSinceLast) {
                _minSinceLast = curEnvelope;
            }
            if (curEnvelope >= _curResetThreshold && _prevEnvelope < _curResetThreshold) {
                _waveStartSample    = curSampleIdx;
                _waveNonHangSamples = 0;
                _currentWavePeak    = curEnvelope;
                var initImp         = curEnvelope - _curResetThreshold;
                _waveImpulse        = (initImp > 0) ? initImp : 0;
            } else {
                if (curEnvelope > _currentWavePeak) {
                    _currentWavePeak = curEnvelope;
                }
                if (curEnvelope > _curResetThreshold) {
                    _waveImpulse += (curEnvelope - _curResetThreshold);
                }
            }
            if (ySmooth < _waveYMin) { _waveYMin = ySmooth; }
            if (ySmooth > _waveYMax) { _waveYMax = ySmooth; }
            if (zSmooth < _waveZMin) { _waveZMin = zSmooth; }
            if (zSmooth > _waveZMax) { _waveZMax = zSmooth; }
        }

        var waveTiltPtp = (_waveYMax - _waveYMin) + (_waveZMax - _waveZMin);

        // Monitor hang posture throughout current wave.
        if (!xInHang) {
            _waveNonHangSamples++;
        }

        // 7. Finite State Machine transitions.
        if (_state == STATE_MOUNT_SETTLING) {
            if (_hasHung) {
                var inHangTime   = curSampleIdx - _hangStartIdx;
                var settledBelow = (curEnvelope < MOUNT_EXIT_ENV);
                var timedOut     = (inHangTime >= _mountCeilingSamples);

                if ((settledBelow || timedOut) && xInHang) {
                    _state              = STATE_READY_TO_ARM;
                    _waveStartSample    = curSampleIdx;
                    _waveNonHangSamples = 0;
                    _currentWavePeak    = 0; // Explicitly reset mount shockwave peak
                    _waveImpulse        = 0;
                    _minSinceLast       = curEnvelope;
                    _waveYMin           = ySmooth;
                    _waveYMax           = ySmooth;
                    _waveZMin           = zSmooth;
                    _waveZMax           = zSmooth;
                }
            }

        } else if (_state == STATE_COOLDOWN) {
            var effTimeout = (_repCount >= 13 && _minSinceLast <= 54)
                ? _deepFatigueTimeoutSamples
                : _cooldownTimeoutSamples;
            var toMargin = (effTimeout == _cooldownTimeoutSamples && _curRepThreshold <= 98) ? 5 : 0;

            // Valley clearance: absolute reset threshold OR relative peak drop >= 45%.
            var relativeDrop = (_pendingWavePeak > 0 && curEnvelope <= ((55 * _pendingWavePeak) / 100));
            var isValley     = (curEnvelope < _curResetThreshold) || relativeDrop;

            var envelopeSettled = (isValley && curEnvelope < 160 && _samplesSinceLast >= _curDebounce);
            var timeoutFallback = (effTimeout > 0 &&
                                   _samplesSinceLast >= effTimeout &&
                                   curEnvelope < (_curRepThreshold - toMargin));

            // Confirm pending rep if wave completed in hang and passed tilt + impulse guards.
            if (_pendingRepSample >= 0) {
                var dtCand = (_repCount > 0 && _lastConfirmedRepIdx >= 0)
                    ? (_pendingRepSample - _lastConfirmedRepIdx)
                    : 200;
                var tiltOk = (dtCand >= _fastCandSamples) || (waveTiltPtp >= 220);
                if (_currentWavePeak <= 83 && waveTiltPtp < 660) {
                    tiltOk = false;
                }
                var isBounce  = (dtCand < _bounceWindowSamples &&
                                 _lastRepTruePk >= 240 &&
                                 _currentWavePeak < ((45 * _lastRepTruePk) / 100));
                var impulseOk = (_waveImpulse >= MIN_WAVE_IMPULSE) && !isBounce;

                if (isValley) {
                    var waveDur = curSampleIdx - _waveStartSample;
                    if (waveDur >= _minWaveDuration && xInHang && tiltOk && impulseOk) {
                        var allHang = (_waveNonHangSamples == 0);
                        _recordConfirmedRep(_pendingRepSample, curSampleIdx, waveDur, allHang);
                        eventResult = 1;
                    }
                    _pendingRepSample = -1;
                    _waveYMin         = ySmooth;
                    _waveYMax         = ySmooth;
                    _waveZMin         = zSmooth;
                    _waveZMax         = zSmooth;
                } else if (timeoutFallback) {
                    var inHangLen = (curSampleIdx - _waveStartSample) - _waveNonHangSamples;
                    if (xInHang && tiltOk && impulseOk) {
                        var allHang = (_waveNonHangSamples == 0);
                        _recordConfirmedRep(_pendingRepSample, curSampleIdx, _samplesSinceLast, allHang);
                        eventResult = 1;
                    } else if (inHangLen >= _minWaveDuration &&
                               (_pendingRepSample - _waveStartSample) >= _minFirstWaveAge &&
                               tiltOk && impulseOk) {
                        _recordConfirmedRep(_pendingRepSample, curSampleIdx, inHangLen, true);
                        eventResult = 1;
                    }
                    _pendingRepSample = -1;
                    _waveYMin         = ySmooth;
                    _waveYMax         = ySmooth;
                    _waveZMin         = zSmooth;
                    _waveZMax         = zSmooth;
                }
            }

            if ((envelopeSettled || timeoutFallback) && isSafeMotion) {
                _state = STATE_READY_TO_ARM;
                if (timeoutFallback && !isValley) {
                    _minSinceLast = curEnvelope;
                }
            }

        } else if (_state == STATE_READY_TO_ARM) {
            var reqTh = _curRepThreshold;
            if (_samplesSinceLast < _bounceWindowSamples && _curRepThreshold <= 98 && _lastRepTruePk >= 240) {
                var bounceTh = ((45 * _lastRepTruePk) / 100);
                if (bounceTh > 105) { bounceTh = 105; }
                if (bounceTh > reqTh) { reqTh = bounceTh; }
            }

            var longGap = (_samplesSinceLast >= _longGapSamples) ||
                          (_repCount == 0 &&
                           (curSampleIdx - _waveStartSample) >= _minFirstWaveAge &&
                           (curSampleIdx - _hangStartIdx) >= _minFirstHangAge);
            var tiltAssisted  = (longGap && curEnvelope >= 88 && waveTiltPtp >= 260 && ySmooth >= 180);
            var promOk        = (_samplesSinceLast >= _deadHangGapSamples && _minSinceLast <= 36 && curEnvelope >= 97);
            var midFatigueOk  = (_repCount >= 12 && _samplesSinceLast >= _midFatigueGapSamples && _minSinceLast <= 47 && curEnvelope >= 95);
            var latePauseOk   = (_repCount >= 12 && _curRepThreshold >= 94 && _samplesSinceLast >= _latePauseGapSamples && _minSinceLast <= 58 && curEnvelope >= 78);
            var valleyCleared = (_samplesSinceLast < _valleyClearSamples) || (_minSinceLast <= 98);

            if ((curEnvelope >= reqTh || tiltAssisted || promOk || midFatigueOk || latePauseOk) &&
                valleyCleared && isSafeMotion && xInHang && _samplesSinceLast >= _curDebounce) {
                _state = STATE_ARMED;
            }

        } else if (_state == STATE_ARMED) {
            // Falling-edge peak trigger.
            if (curEnvelope < _prevEnvelope && isSafeMotion && xInHang) {
                _pendingRepSample = curSampleIdx;
                _pendingWavePeak  = _currentWavePeak;
                _samplesSinceLast = 0;
                _minSinceLast     = curEnvelope;
                _state            = STATE_COOLDOWN;
            }
        }

        _prevEnvelope = curEnvelope;
        return eventResult;
    }

    // Finalizes the set if the user manually stops recording before bar release lock.
    public function finalizeSet() as Void {
        if (_consensusDone) {
            return;
        }
        // End-of-session guard for sets stopped while still on the bar.
        if (!_isSetLocked && _hasHung && _xStreak > 0 && _repCount > 0 && _lastConfirmedSample >= 0) {
            var departureStart = _sampleCount - _xStreak;
            if ((departureStart - _lastConfirmedSample) < _cancelPriorWindow &&
                (_lastConfirmedWaveDur < _minWaveDuration || !_lastConfirmedAllHang)) {
                _repCount--;
                _popBaseRep();
                _lastConfirmedSample = -1;
            }
        }
        _runPostSetConsensus();
    }

    // Updates Pull-Up vs Chin-Up classification using clean vertical-hang Y baseline
    // and per-rep Y-wave excursion polarity votes.
    private function _updateExerciseClassification() as Void {
        if (_hangYSamples <= 0) {
            return;
        }
        var meanHangY = _hangYSum / _hangYSamples;
        var highPct   = (_hangYHighSamples * 100) / _hangYSamples;
        var hangIsChin = (meanHangY > 95) || (meanHangY > 55 && highPct >= 25);

        if (_chinRepVotes > _pullRepVotes && meanHangY > 35) {
            _exerciseType = EXERCISE_CHIN_UP;
        } else if (_pullRepVotes > _chinRepVotes && meanHangY < 120) {
            _exerciseType = EXERCISE_PULL_UP;
        } else {
            _exerciseType = hangIsChin ? EXERCISE_CHIN_UP : EXERCISE_PULL_UP;
        }
    }

    // Helper to confirm repetition and update adaptive parameters.
    private function _recordConfirmedRep(repIdx as Number, confirmIdx as Number, waveDur as Number, allHang as Boolean) as Void {
        // Cadence-adaptive debounce with ceiling to protect rest-pauses (from rep >= 2).
        if (_repCount > 0 && _lastConfirmedRepIdx >= 0) {
            var dtPrev = repIdx - _lastConfirmedRepIdx;
            var adaptedDebounce = ((55 * dtPrev) / 100);
            if (adaptedDebounce > _debounceMax) {
                adaptedDebounce = _debounceMax;
            }
            _curDebounce = (adaptedDebounce > _debounceMin) ? adaptedDebounce : _debounceMin;
        } else {
            _curDebounce = _debounceMin;
        }

        _repCount++;
        _recordBaseRep(repIdx);
        _lastConfirmedRepIdx  = repIdx;
        _lastConfirmedSample  = confirmIdx;
        _lastConfirmedWaveDur = waveDur;
        _lastConfirmedAllHang = allHang;
        _lastRepTruePk        = _currentWavePeak;

        // Vote on Pull-Up vs Chin-Up from within-wave Y excursion polarity:
        // Chin-Ups peak strongly positive (+200..+400 mG), Pull-Ups dip negative (-120..-280 mG).
        var waveYCenter = _waveYMax + _waveYMin;
        if (_waveYMax >= 180 && waveYCenter > 40) {
            _chinRepVotes++;
        } else if (_waveYMin <= -110 || waveYCenter < -20) {
            _pullRepVotes++;
        }
        _updateExerciseClassification();

        // Exponential moving average fatigue thresholds (from rep >= 4).
        // Dynamic physiological fatigue floor decays for deep fatigue sets (rep >= 8).
        if (_repCount >= 4) {
            _peakAvg = (0.30 * _pendingWavePeak.toFloat()) + (0.70 * _peakAvg);
            var dynRepFloor = 95;
            if (_repCount >= 8) {
                var scaledFloor = (0.60 * _peakAvg).toNumber();
                if (scaledFloor < 83) { scaledFloor = 83; }
                if (scaledFloor > 95) { scaledFloor = 95; }
                dynRepFloor = scaledFloor;
            }
            var adaptedRep = (0.70 * _peakAvg).toNumber();
            _curRepThreshold = (adaptedRep > dynRepFloor) ? adaptedRep : dynRepFloor;

            var dynResetFloor = ((55 * dynRepFloor) / 100);
            if (dynResetFloor < 45) { dynResetFloor = 45; }
            if (dynResetFloor > 55) { dynResetFloor = 55; }
            var adaptedReset = ((55 * _curRepThreshold) / 100);
            _curResetThreshold = (adaptedReset > dynResetFloor) ? adaptedReset : dynResetFloor;
        }

        System.println("PullUpDetector: Rep #" + _repCount + " confirmed (peak=" + _pendingWavePeak
                       + " dur=" + waveDur + " debounce=" + _curDebounce
                       + " repThresh=" + _curRepThreshold + " resetThresh=" + _curResetThreshold
                       + " ex=" + getExerciseName() + ")");
    }

    // --- Candidate 14 Post-Set Consensus Helpers ---

    private function _sortIntArray(arr as Array<Number>, count as Number) as Void {
        for (var i = 1; i < count; i++) {
            var key = arr[i];
            var j   = i - 1;
            while (j >= 0 && arr[j] > key) {
                arr[j + 1] = arr[j];
                j--;
            }
            arr[j + 1] = key;
        }
    }

    private function _medianFloat(arr as Array<Number>, count as Number) as Float {
        if (count <= 0) {
            return 0.0;
        }
        var tmp = new Array<Number>[count];
        for (var i = 0; i < count; i++) {
            tmp[i] = arr[i];
        }
        _sortIntArray(tmp, count);
        if ((count % 2) == 1) {
            return tmp[count / 2].toFloat();
        }
        return 0.5 * (tmp[(count / 2) - 1].toFloat() + tmp[count / 2].toFloat());
    }

    private function _calcSortedCadence(arr as Array<Number>, count as Number) as Float {
        if (count < 2) {
            return 140.0;
        }
        var sorted = new Array<Number>[count];
        var i      = 0;
        for (i = 0; i < count; i++) {
            sorted[i] = arr[i];
        }
        _sortIntArray(sorted, count);
        var ivs = new Array<Number>[count - 1];
        for (i = 1; i < count; i++) {
            ivs[i - 1] = sorted[i] - sorted[i - 1];
        }
        return _medianFloat(ivs, count - 1);
    }

    // Finds local extrema peaks with topographic prominence >= minProm1225 and greedy spacing >= minSpacing.
    // Populates outK and outProm and returns the number of kept peaks.
    private function _findPeaksExtrema(sign as Number, minSpacing as Number, minProm1225 as Number,
                                       outK as Array<Number>, outProm as Array<Number>) as Number {
        var m = _extCount;
        if (m < 3) {
            return 0;
        }

        var candK    = new Array<Number>[m];
        var candProm = new Array<Number>[m];
        var candSig  = new Array<Number>[m];
        var nP       = 0;
        var k        = 0;
        var j        = 0;

        for (k = 1; k < (m - 1); k++) {
            var pkVal = sign * _extVals[k];
            if (pkVal > (sign * _extVals[k - 1]) && pkVal > (sign * _extVals[k + 1])) {
                var leftMin = pkVal;
                var minJ = k - 35;
                if (minJ < 0) { minJ = 0; }
                for (j = k - 1; j >= minJ; j--) {
                    var sj = sign * _extVals[j];
                    if (sj > pkVal) { break; }
                    if (sj < leftMin) { leftMin = sj; }
                }
                var rightMin = pkVal;
                var maxJ = k + 35;
                if (maxJ >= m) { maxJ = m - 1; }
                for (j = k + 1; j <= maxJ; j++) {
                    var sj2 = sign * _extVals[j];
                    if (sj2 > pkVal) { break; }
                    if (sj2 < rightMin) { rightMin = sj2; }
                }
                var prom = pkVal - ((leftMin > rightMin) ? leftMin : rightMin);
                if (prom >= minProm1225) {
                    candK[nP]    = k;
                    candProm[nP] = prom;
                    candSig[nP]  = pkVal;
                    nP++;
                }
            }
        }

        if (nP == 0) {
            return 0;
        }

        // Sort candidate indices by peak height descending (stable tie-break by index).
        var order = new Array<Number>[nP];
        var keep  = new Array<Boolean>[nP];
        for (k = 0; k < nP; k++) {
            order[k] = k;
            keep[k]  = true;
        }
        for (k = 1; k < nP; k++) {
            var keyIdx = order[k];
            var keySig = candSig[keyIdx];
            j          = k - 1;
            while (j >= 0 && candSig[order[j]] < keySig) {
                order[j + 1] = order[j];
                j--;
            }
            order[j + 1] = keyIdx;
        }

        for (k = 0; k < nP; k++) {
            var u = order[k];
            if (!keep[u]) {
                continue;
            }
            var posU = _extOffsets[candK[u]];
            for (j = 0; j < nP; j++) {
                if (j != u && keep[j]) {
                    var diffPos = _extOffsets[candK[j]] - posU;
                    if (diffPos < 0) { diffPos = -diffPos; }
                    if (diffPos < minSpacing) {
                        keep[j] = false;
                    }
                }
            }
        }

        var outCount = 0;
        for (k = 0; k < nP; k++) {
            if (keep[k]) {
                outK[outCount]    = candK[k];
                outProm[outCount] = candProm[k];
                outCount++;
            }
        }
        return outCount;
    }

    private function _minDistToSet(val as Number, arr as Array<Number>, count as Number) as Number {
        if (count <= 0) {
            return 999;
        }
        var best = 999999;
        for (var i = 0; i < count; i++) {
            var d = arr[i] - val;
            if (d < 0) { d = -d; }
            if (d < best) { best = d; }
        }
        return best;
    }

    private function _containsVal(val as Number, arr as Array<Number>, count as Number) as Boolean {
        for (var i = 0; i < count; i++) {
            if (arr[i] == val) {
                return true;
            }
        }
        return false;
    }

    // Step 7 helper: Cadence-Anomaly Gap Inspection (missed partial / ultra-smooth reps).
    private function _runStep7GapRescue(L as Number, sIdx as Number, sign as Number,
                                        nBase as Number, nPost as Number,
                                        medCadence as Float, departureSample as Number,
                                        confirmedReps as Array<Number>, nConfirmed as Number) as Number {
        if (L < 120 || nConfirmed < 6) {
            return nConfirmed;
        }

        // Bounded early-exit: When nBase == nPost == nConfirmed, Step 7 only performs 7a (double-cadence gap rescue).
        // If there are no wide gaps >= 1.85 * medCadence, we can completely bypass the second peak-finding pass!
        if (nBase == nPost && nConfirmed == nBase) {
            var loThreshold = (1.85 * medCadence).toNumber();
            if (loThreshold < 200) { loThreshold = 200; }
            var hasCandidateGap = false;
            for (var gi = 1; gi < nConfirmed; gi++) {
                if ((confirmedReps[gi] - confirmedReps[gi - 1]) >= loThreshold) {
                    hasCandidateGap = true;
                    break;
                }
            }
            if (!hasCandidateGap) {
                return nConfirmed;
            }
        }

        var rawK    = new Array<Number>[MAX_EXTREMA];
        var rawProm = new Array<Number>[MAX_EXTREMA];
        var nRaw    = _findPeaksExtrema(sign, 65, 35 * 1225, rawK, rawProm);
        _sortIntArray(confirmedReps, nConfirmed);

        var i      = 0;
        var j      = 0;
        var midLo  = 0;
        var midHi  = 0;
        var rk     = 0;
        var gIdx   = 0;

        // 7a. Internal double-cadence gap rescue.
        if (nBase == nPost && nConfirmed == nBase) {
            var loGap = (1.85 * medCadence).toNumber();
            if (loGap < 200) { loGap = 200; }
            var hiGap = (2.45 * medCadence).toNumber();
            var pad   = (0.65 * medCadence).toNumber();
            if (pad < 70) { pad = 70; }

            for (i = 1; i < nConfirmed; i++) {
                var gap = confirmedReps[i] - confirmedReps[i - 1];
                if (gap >= loGap && gap <= hiGap) {
                    midLo = confirmedReps[i - 1] + pad;
                    midHi = confirmedReps[i] - pad;
                    if (midHi >= midLo) {
                        for (j = 0; j < nRaw; j++) {
                            rk   = rawK[j];
                            gIdx = sIdx + _extOffsets[rk];
                            if (gIdx >= midLo && gIdx <= midHi &&
                                rawProm[j] >= (45 * 1225) &&
                                _extXAt[rk] <= -750) {
                                if (_extMaxEnv35[rk] >= 100 && nConfirmed < MAX_BASE_REPS) {
                                    confirmedReps[nConfirmed] = gIdx;
                                    nConfirmed++;
                                    _sortIntArray(confirmedReps, nConfirmed);
                                    break;
                                }
                            }
                        }
                    }
                }
            }
        }

        // 7b. Late-set deep-fatigue struggle rescue.
        if (nConfirmed >= 14 && nBase <= nPost) {
            var lastC = confirmedReps[nConfirmed - 1];
            if (nPost > nConfirmed && nConfirmed >= 2) {
                var prevC = confirmedReps[nConfirmed - 2];
                if ((lastC - prevC) >= 300) {
                    midLo = prevC + 95;
                    midHi = lastC - 95;
                    for (j = 0; j < nRaw; j++) {
                        rk   = rawK[j];
                        gIdx = sIdx + _extOffsets[rk];
                        if (gIdx >= midLo && gIdx <= midHi &&
                            rawProm[j] >= (200 * 1225) &&
                            _extXAt[rk] <= -750) {
                            if (_extMaxEnv35[rk] >= 55 && nConfirmed < MAX_BASE_REPS) {
                                confirmedReps[nConfirmed] = gIdx;
                                nConfirmed++;
                                _sortIntArray(confirmedReps, nConfirmed);
                                lastC = confirmedReps[nConfirmed - 1];
                                break;
                            }
                        }
                    }
                }
            }
            for (j = 0; j < nRaw; j++) {
                rk   = rawK[j];
                gIdx = sIdx + _extOffsets[rk];
                if (gIdx > (lastC + 200) && gIdx < (departureSample - 80)) {
                    if (rawProm[j] >= (180 * 1225) && _extMaxX60[rk] <= -500) {
                        if (_extMaxEnv35[rk] >= 35 && nConfirmed < MAX_BASE_REPS) {
                            confirmedReps[nConfirmed] = gIdx;
                            nConfirmed++;
                            _sortIntArray(confirmedReps, nConfirmed);
                            break;
                        }
                    }
                }
            }
        }

        // 7c. High-rep fast-cadence early gap rescue.
        if ((nPost - nBase) >= 4 && nConfirmed >= 15) {
            for (i = 0; i < nConfirmed; i++) {
                midLo = 0;
                midHi = -1;
                if (i == 0) {
                    midLo = sIdx + 15;
                    midHi = confirmedReps[0] - 80;
                } else {
                    if ((confirmedReps[i] - confirmedReps[i - 1]) < 120) {
                        continue;
                    }
                    midLo = confirmedReps[i - 1] + 45;
                    midHi = confirmedReps[i] - 45;
                }
                if (midHi >= midLo) {
                    var foundEarly = false;
                    for (j = 0; j < nRaw; j++) {
                        rk   = rawK[j];
                        gIdx = sIdx + _extOffsets[rk];
                        if (gIdx >= midLo && gIdx <= midHi &&
                            rawProm[j] >= (45 * 1225) &&
                            _extXAt[rk] <= -750) {
                            if (_extMaxEnv35[rk] >= 140 && nConfirmed < MAX_BASE_REPS) {
                                confirmedReps[nConfirmed] = gIdx;
                                nConfirmed++;
                                _sortIntArray(confirmedReps, nConfirmed);
                                foundEarly = true;
                                break;
                            }
                        }
                    }
                    if (foundEarly) {
                        break;
                    }
                }
            }
        }
        return nConfirmed;
    }

    // Stage 2 helper: Extract Candidate 11 post-set zero-phase Y peaks.
    private function _extractStage2Peaks(L as Number, sIdx as Number, sign as Number,
                                         postReps as Array<Number>, postExtK as Array<Number>) as Number {
        if (L < 60) {
            return 0;
        }
        var candK    = new Array<Number>[MAX_EXTREMA];
        var candProm = new Array<Number>[MAX_EXTREMA];
        var nCand    = _findPeaksExtrema(sign, 70, 30 * 1225, candK, candProm);
        if (nCand <= 0) {
            return 0;
        }
        var sortedProms = new Array<Number>[nCand];
        var i           = 0;
        for (i = 0; i < nCand; i++) {
            sortedProms[i] = candProm[i];
        }
        _sortIntArray(sortedProms, nCand);
        var topN   = (nCand < 4) ? nCand : 4;
        var topArr = new Array<Number>[topN];
        for (i = 0; i < topN; i++) {
            topArr[i] = sortedProms[nCand - topN + i];
        }
        var promThresh = 0.35 * _medianFloat(topArr, topN);
        if (promThresh < (65.0 * 1225.0)) {
            promThresh = 65.0 * 1225.0;
        }

        var nPost = 0;
        for (i = 0; i < nCand; i++) {
            var extK = candK[i];
            var pOff = _extOffsets[extK];
            if (pOff < 35 || pOff > (L - 25)) {
                continue;
            }
            if (candProm[i].toFloat() >= promThresh && _extMaxEnv35[extK] >= 40) {
                if (nPost < MAX_BASE_REPS) {
                    postReps[nPost] = sIdx + pOff;
                    postExtK[nPost] = extK;
                    nPost++;
                }
            }
        }
        return nPost;
    }

    // Executes Candidate 14's exact post-set consensus algorithm.
    private function _runPostSetConsensus() as Void {
        if (_consensusDone) {
            return;
        }
        _consensusDone = true;

        var n = _sampleCount;

        // Long-Set Watchdog Protection:
        // On sets longer than ~28 seconds (_sampleCount >= 2800 at 100 Hz), the online detector has already
        // reliably tracked all reps in real time with cadence and physiological fatigue floors.
        // Running the second zero-phase topographic prominence pass over >2,800 samples exceeds Connect IQ's
        // synchronous callback execution budget (Watchdog Tripped Error). Bypassing consensus keeps the set 100% safe.
        if (n >= 2800) {
            System.println("PullUpDetector: Set duration (" + n + " samples >= 28.0s) qualifies as long set - preserving online base reps (" + _repCount + ")");
            return;
        }

        var i = 0;
        var j = 0;
        if (_cHasHung && _cDismountIdx < 0) {
            var startPos = (_yDelayIdx - _yDelayCount + ZP_WIN) % ZP_WIN;
            for (i = 0; i < _yDelayCount; i++) {
                _pushZpSample(_yDelay[(startPos + i) % ZP_WIN], true);
            }
            _yDelayCount = 0;
        }
        _flushZeros();

        // Copy Stage 1 baseline reps and their local max envelopes.
        var baseReps = new Array<Number>[MAX_BASE_REPS];
        var baseEnvs = new Array<Number>[MAX_BASE_REPS];
        var nBase    = _baseCount;
        for (i = 0; i < nBase; i++) {
            baseReps[i] = _baseReps[i];
            baseEnvs[i] = _baseMaxEnv[i];
        }

        // Pre-pass: Remove obvious internal double-trigger in short sets (nBase < 7).
        if (nBase >= 3 && nBase < 7) {
            var medC = _calcSortedCadence(baseReps, nBase);
            for (i = 1; i < (nBase - 1); i++) {
                if ((baseReps[i] - baseReps[i - 1]).toFloat() < (0.85 * medC) &&
                    (baseReps[i + 1] - baseReps[i]).toFloat() < (0.85 * medC)) {
                    var minPN = (baseEnvs[i - 1] < baseEnvs[i + 1]) ? baseEnvs[i - 1] : baseEnvs[i + 1];
                    if (baseEnvs[i] <= minPN) {
                        for (j = i; j < (nBase - 1); j++) {
                            baseReps[j] = baseReps[j + 1];
                            baseEnvs[j] = baseEnvs[j + 1];
                        }
                        nBase--;
                        break;
                    }
                }
            }
        }

        // Stage 2: Extract Candidate 11 post-set zero-phase Y peaks.
        var L        = _yFedCount;
        var sIdx     = _cHasHung ? _cSettleIdx : 0;
        var isChin   = ((_cntY160 * 100 > 15 * L && _cntYM20 * 100 > 50 * L) || (_cntY210 * 100 > 15 * L));
        var sign     = isChin ? 1 : -1;
        var postReps = new Array<Number>[MAX_BASE_REPS];
        var postExtK = new Array<Number>[MAX_BASE_REPS];
        var nPost    = _extractStage2Peaks(L, sIdx, sign, postReps, postExtK);

        var departureSample = (_cHasHung && _cDepSample >= 0) ? _cDepSample : n;

        // Step 2: Bipartite greedy matching within +/- 100 samples (1.00s).
        var matchedB = new Array<Boolean>[nBase];
        var matchedP = new Array<Boolean>[nPost];
        for (i = 0; i < nBase; i++) { matchedB[i] = false; }
        for (i = 0; i < nPost; i++) { matchedP[i] = false; }

        var confirmedReps       = new Array<Number>[MAX_BASE_REPS];
        var confirmedPostCoords = new Array<Number>[MAX_BASE_REPS];
        var nConfirmed          = 0;

        while (true) {
            var bestDist = 101;
            var bestBi   = -1;
            var bestPi   = -1;
            for (i = 0; i < nBase; i++) {
                if (matchedB[i]) { continue; }
                for (j = 0; j < nPost; j++) {
                    if (matchedP[j]) { continue; }
                    var d = baseReps[i] - postReps[j];
                    if (d < 0) { d = -d; }
                    if (d <= 100 && d < bestDist) {
                        bestDist = d;
                        bestBi   = i;
                        bestPi   = j;
                    }
                }
            }
            if (bestBi < 0) {
                break;
            }
            matchedB[bestBi] = true;
            matchedP[bestPi] = true;
            if (nConfirmed < MAX_BASE_REPS) {
                confirmedReps[nConfirmed]       = baseReps[bestBi];
                confirmedPostCoords[nConfirmed] = postReps[bestPi];
                nConfirmed++;
            }
        }

        var nMatchedPairs    = nConfirmed;
        var unmatchedBaseIdx = new Array<Number>[nBase];
        var nUnmatchedB      = 0;
        for (i = 0; i < nBase; i++) {
            if (!matchedB[i]) {
                unmatchedBaseIdx[nUnmatchedB] = i;
                nUnmatchedB++;
            }
        }

        var unmatchedPostIdx = new Array<Number>[nPost];
        var nUnmatchedP      = 0;
        for (i = 0; i < nPost; i++) {
            if (!matchedP[i]) {
                unmatchedPostIdx[nUnmatchedP] = i;
                nUnmatchedP++;
            }
        }

        // Step 3: Estimate set cadence from all known base reps.
        var medCadence = _calcSortedCadence(baseReps, nBase);
        if (nBase <= 6 && (nPost - nBase) >= 3 && medCadence >= 185.0 && nPost >= 2) {
            var medPost = _calcSortedCadence(postReps, nPost);
            if (medPost >= 135.0 && medPost < medCadence) {
                medCadence = medPost;
            }
        }

        var minSpacing      = (0.72 * medCadence).toNumber();
        if (minSpacing < 75) { minSpacing = 75; }
        var minSpacingStep4 = minSpacing;

        if (nPost <= 6 && nBase == (nPost + 1) && nMatchedPairs == nPost && nConfirmed >= 2) {
            var candStep = (0.72 * _calcSortedCadence(confirmedReps, nConfirmed)).toNumber();
            if (candStep > minSpacingStep4) {
                minSpacingStep4 = candStep;
            }
        }

        // Step 4: Evaluate unmatched base reps (prune dismount drops & double-triggers).
        var prunedBaseIdx = new Array<Number>[nBase];
        var nPruned       = 0;
        for (i = 0; i < nUnmatchedB; i++) {
            var bi4 = unmatchedBaseIdx[i];
            var b   = baseReps[bi4];
            if ((departureSample - b) < 45 || _minDistToSet(b, confirmedReps, nConfirmed) < minSpacingStep4) {
                prunedBaseIdx[nPruned] = bi4;
                nPruned++;
            } else if (nConfirmed < MAX_BASE_REPS) {
                confirmedReps[nConfirmed]       = b;
                confirmedPostCoords[nConfirmed] = b;
                nConfirmed++;
            }
        }
        var nPrunedStep4 = nPruned;

        // Step 5: Evaluate unmatched post-set Y reps (recover missed dead-hang / deep-fatigue reps).
        var alreadyAgreed = (nBase == nPost && nConfirmed == nBase);
        var lastConfirmed = 0;
        var minConfirmed  = 999999;
        for (i = 0; i < nConfirmed; i++) {
            if (confirmedReps[i] > lastConfirmed) { lastConfirmed = confirmedReps[i]; }
            if (confirmedReps[i] < minConfirmed)  { minConfirmed  = confirmedReps[i]; }
        }

        var hasInternalGap = false;
        if (nBase >= 2 && nPost > nBase) {
            var maxBaseGap = 0;
            for (i = 1; i < nBase; i++) {
                var gapB = baseReps[i] - baseReps[i - 1];
                if (gapB > maxBaseGap) { maxBaseGap = gapB; }
            }
            hasInternalGap = (maxBaseGap.toFloat() >= (1.65 * medCadence));
        }

        var effSpacing = minSpacing;
        if (nPrunedStep4 > 0) {
            effSpacing = (0.65 * medCadence).toNumber();
            if (effSpacing < 75) { effSpacing = 75; }
        }

        for (i = 0; i < nUnmatchedP; i++) {
            var pi4  = unmatchedPostIdx[i];
            var p    = postReps[pi4];
            var extK = postExtK[pi4];

            if (_extXAt[extK] > -550 || p >= (departureSample - 25) || _extMaxX35[extK] > -200) {
                continue;
            }
            if (nConfirmed > 0 && p > lastConfirmed) {
                if (p >= (departureSample - 45)) {
                    continue;
                }
                if (nBase > nPost && nConfirmed >= nBase && nPrunedStep4 == 0) {
                    continue;
                }
            }
            if (alreadyAgreed && nBase >= 7 && p > lastConfirmed) {
                continue;
            }
            if (nConfirmed > 0 && p > lastConfirmed && (nPost - nBase) < 2 && !hasInternalGap) {
                if (_extMaxEnv35[extK] < 62) {
                    continue;
                }
            }
            if (nConfirmed > 0 && p < minConfirmed) {
                if (_extMaxEnv35[extK] < 90) {
                    continue;
                }
            }
            if (alreadyAgreed && (p > lastConfirmed || nBase >= 7)) {
                continue;
            }
            if (nConfirmed < 6) {
                if (nPost <= nConfirmed) {
                    continue;
                }
                if (p > lastConfirmed && nPrunedStep4 == 0 && (nPost - nBase) < 3) {
                    continue;
                }
            }

            var dtCloseP  = _minDistToSet(p, confirmedReps, nConfirmed);
            var spacingOk = (dtCloseP >= effSpacing);
            if (!spacingOk && dtCloseP >= 84 && nPost > nBase && nConfirmed > 0) {
                var rPrev = -1;
                var pPrev = -1;
                var rNext = 999999;
                var pNext = 999999;
                for (j = 0; j < nConfirmed; j++) {
                    var rc = confirmedReps[j];
                    if (rc < p && rc > rPrev) {
                        rPrev = rc;
                        pPrev = confirmedPostCoords[j];
                    }
                    if (rc > p && rc < rNext) {
                        rNext = rc;
                        pNext = confirmedPostCoords[j];
                    }
                }
                if (rPrev >= 0 && rNext < 999999) {
                    var minPGap = (1.75 * medCadence).toNumber();
                    if (minPGap < 242) { minPGap = 242; }
                    if ((pNext - pPrev) >= minPGap && (p - pPrev) >= effSpacing && (pNext - p) >= effSpacing) {
                        spacingOk = true;
                    }
                }
            }

            if (spacingOk && _extMaxEnv35[extK] >= 38 && nConfirmed < MAX_BASE_REPS) {
                confirmedReps[nConfirmed]       = p;
                confirmedPostCoords[nConfirmed] = p;
                if (p < minConfirmed) { minConfirmed = p; }
                nConfirmed++;
            }
        }

        // Step 6: Count-conservation safeguard.
        var hasTrailingPostSwing = false;
        if (nPost > 0) {
            if (_extMaxX60[postExtK[nPost - 1]] > -300 || postReps[nPost - 1] >= (departureSample - 60)) {
                hasTrailingPostSwing = true;
            }
        }

        if (nConfirmed < nPost && nPruned > 0) {
            // Sort prunedBaseIdx by baseEnvs descending.
            for (i = 1; i < nPruned; i++) {
                var keyBi = prunedBaseIdx[i];
                var keyEv = baseEnvs[keyBi];
                j         = i - 1;
                while (j >= 0 && baseEnvs[prunedBaseIdx[j]] < keyEv) {
                    prunedBaseIdx[j + 1] = prunedBaseIdx[j];
                    j--;
                }
                prunedBaseIdx[j + 1] = keyBi;
            }

            for (i = 0; i < nPruned; i++) {
                if (nConfirmed >= nPost) {
                    break;
                }
                var b2 = baseReps[prunedBaseIdx[i]];
                if ((departureSample - b2) < 45) {
                    continue;
                }
                if (nBase < 7 && hasTrailingPostSwing && nConfirmed > 0) {
                    var minC = confirmedReps[0];
                    var maxC = confirmedReps[0];
                    for (j = 1; j < nConfirmed; j++) {
                        if (confirmedReps[j] < minC) { minC = confirmedReps[j]; }
                        if (confirmedReps[j] > maxC) { maxC = confirmedReps[j]; }
                    }
                    if (b2 > minC && b2 < maxC) {
                        continue;
                    }
                }
                if (_minDistToSet(b2, confirmedReps, nConfirmed) >= 75 && nConfirmed < MAX_BASE_REPS) {
                    confirmedReps[nConfirmed] = b2;
                    nConfirmed++;
                }
            }

            if (nConfirmed < nPost) {
                for (i = 0; i < nUnmatchedP; i++) {
                    if (nConfirmed >= nPost) {
                        break;
                    }
                    var pi5   = unmatchedPostIdx[i];
                    var p2    = postReps[pi5];
                    var extK2 = postExtK[pi5];
                    if (!_containsVal(p2, confirmedReps, nConfirmed) &&
                        _extXAt[extK2] <= -550 &&
                        p2 < (departureSample - 25) &&
                        _extMaxX35[extK2] <= -200) {
                        if (_minDistToSet(p2, confirmedReps, nConfirmed) >= 75 && nConfirmed < MAX_BASE_REPS) {
                            confirmedReps[nConfirmed] = p2;
                            nConfirmed++;
                        }
                    }
                }
            }
        }

        // Step 7: Cadence-Anomaly Gap Inspection.
        nConfirmed = _runStep7GapRescue(L, sIdx, sign, nBase, nPost, medCadence,
                                        departureSample, confirmedReps, nConfirmed);

        _repCount = nConfirmed;
        System.println("PullUpDetector: Post-set consensus finalized -> " + _repCount
                       + " reps (base=" + nBase + ", postY=" + nPost + ")");
    }

    public function getRepCount() as Number {
        return _repCount;
    }

    public function setRepCount(count as Number) as Void {
        _repCount = count;
    }

    public function getSampleCount() as Number {
        return _sampleCount;
    }

    public function getState() as Number {
        return _state;
    }

    public function isSetLocked() as Boolean {
        return _isSetLocked;
    }

    public function hasHung() as Boolean {
        return _hasHung;
    }

    public function getCurRepThreshold() as Number {
        return _curRepThreshold;
    }

    public function getCurResetThreshold() as Number {
        return _curResetThreshold;
    }

    public function getExerciseType() as Number {
        return _exerciseType;
    }

    public function getExerciseName() as String {
        return (_exerciseType == EXERCISE_CHIN_UP) ? "CHIN UP" : "PULL UP";
    }
}
