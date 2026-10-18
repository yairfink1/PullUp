import Toybox.Graphics;
import Toybox.Lang;
import Toybox.System;

// ---------------------------------------------------------------------------
// PageIndicator - draws native-style page dots on the left edge (9 o'clock).
//
// Used by PullUpView, PullUpMultiSetView, and PullUpHistoryView to show current
// page position within the 3-page layout. Auto-hides after TIMEOUT_MS milliseconds.
// ---------------------------------------------------------------------------
module PageIndicator {

    // Duration (ms) the indicator remains visible after user interaction.
    const TIMEOUT_MS = 3000;

    // Dot geometry.
    const DOT_RADIUS   = 4;
    const DOT_SPACING  = 14;    // Center-to-center vertical spacing.
    const DOT_MARGIN_X = 12;    // Horizontal inset from the left edge.

    // Returns true if the page indicator should still be visible based on
    // elapsed time since the last user interaction.
    function isVisible(lastInteractionTime as Number) as Boolean {
        var elapsed = System.getTimer() - lastInteractionTime;
        return (elapsed < TIMEOUT_MS);
    }

    // Draws a vertical stack of page dots centred at the 9 o'clock position.
    //   currentPage - zero-based index of the active page.
    //   totalPages  - total number of pages.
    function draw(dc as Graphics.Dc, currentPage as Number, totalPages as Number) as Void {
        var h  = dc.getHeight();
        var cy = h / 2;

        // Calculate the top of the dot stack so that it's vertically centred.
        var totalHeight = (totalPages - 1) * DOT_SPACING;
        var startY = cy - totalHeight / 2;

        for (var i = 0; i < totalPages; i++) {
            var dotY = startY + i * DOT_SPACING;
            if (i == currentPage) {
                // Active page dot: bright white, filled.
                dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
                dc.fillCircle(DOT_MARGIN_X, dotY, DOT_RADIUS);
            } else {
                // Inactive page dot: dim gray, filled.
                dc.setColor(Graphics.COLOR_DK_GRAY, Graphics.COLOR_TRANSPARENT);
                dc.fillCircle(DOT_MARGIN_X, dotY, DOT_RADIUS);
            }
        }
    }
}
