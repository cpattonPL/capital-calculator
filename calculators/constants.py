from enum import Enum


class RatingBucket(str, Enum):
    """
    Canonical rating buckets used across UI and calculations.
    Values are stable internal identifiers.
    Labels are handled in the UI.
    """

    AAA_AA = "AAA_AA"
    A = "A"
    BBB = "BBB"
    BB_B = "BB_B"
    BELOW_B = "BELOW_B"
    UNRATED = "UNRATED"

    @property
    def label(self) -> str:
        """
        Human-readable label for UI display.
        """
        return {
            RatingBucket.AAA_AA: "AAA to AA-",
            RatingBucket.A: "A+ to A-",
            RatingBucket.BBB: "BBB+ to BBB-",
            RatingBucket.BB_B: "BB+ to B-",
            RatingBucket.BELOW_B: "Below B-",
            RatingBucket.UNRATED: "Unrated",
        }[self]
