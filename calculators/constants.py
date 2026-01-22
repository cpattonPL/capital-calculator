from enum import Enum


class RatingBucket(str, Enum):
    """
    Canonical rating buckets used across UI and calculations.
    Values are stable internal identifiers.
    """

    AAA_AA = "AAA_AA"
    A = "A"
    BBB = "BBB"
    BB_B = "BB_B"
    BELOW_B = "BELOW_B"
    UNRATED = "UNRATED"

    @property
    def label(self) -> str:
        return {
            RatingBucket.AAA_AA: "AAA to AA-",
            RatingBucket.A: "A+ to A-",
            RatingBucket.BBB: "BBB+ to BBB-",
            RatingBucket.BB_B: "BB+ to B-",
            RatingBucket.BELOW_B: "Below B-",
            RatingBucket.UNRATED: "Unrated",
        }[self]


class ExposureType(str, Enum):
    """
    Canonical exposure types used across UI and calculations.
    """

    CORPORATE = "CORPORATE"
    RETAIL = "RETAIL"
    RESIDENTIAL_MORTGAGE = "RESIDENTIAL_MORTGAGE"
    COMMERCIAL_REAL_ESTATE = "COMMERCIAL_REAL_ESTATE"
    SOVEREIGN_CENTRAL_BANK = "SOVEREIGN_CENTRAL_BANK"
    BANK = "BANK"
    OTHER = "OTHER"

    @property
    def label(self) -> str:
        return {
            ExposureType.CORPORATE: "Corporate",
            ExposureType.RETAIL: "Retail",
            ExposureType.RESIDENTIAL_MORTGAGE: "Residential Mortgage",
            ExposureType.COMMERCIAL_REAL_ESTATE: "Commercial Real Estate",
            ExposureType.SOVEREIGN_CENTRAL_BANK: "Sovereign / Central Bank",
            ExposureType.BANK: "Bank",
            ExposureType.OTHER: "Other",
        }[self]
