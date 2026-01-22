# calculators/constants.py

from enum import Enum


class RatingBucket(str, Enum):
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


class Approach(str, Enum):
    """
    Canonical approach enum.

    Properties:
      - label: UI label
      - regime: 'basel2' or 'basel3'
      - method: 'standardized' or 'irb'
    """

    BASEL_II_STANDARDIZED = "BASEL_II_STANDARDIZED"
    BASEL_II_IRB = "BASEL_II_IRB"

    BASEL_III_STANDARDIZED = "BASEL_III_STANDARDIZED"

    BASEL_III_IRB_FOUNDATION = "BASEL_III_IRB_FOUNDATION"
    BASEL_III_IRB_ADVANCED = "BASEL_III_IRB_ADVANCED"

    # Backward-compat alias: older code might reference BASEL_III_IRB
    BASEL_III_IRB = "BASEL_III_IRB_FOUNDATION"

    @property
    def label(self) -> str:
        return {
            Approach.BASEL_II_STANDARDIZED: "Basel II - Standardized",
            Approach.BASEL_II_IRB: "Basel II - IRB (Foundation)",

            Approach.BASEL_III_STANDARDIZED: "Basel III - Standardized",

            Approach.BASEL_III_IRB_FOUNDATION: "Basel III - IRB (Foundation) + Output Floor",
            Approach.BASEL_III_IRB_ADVANCED: "Basel III - IRB (Advanced) + Output Floor",
        }[self]

    @property
    def regime(self) -> str:
        return {
            Approach.BASEL_II_STANDARDIZED: "basel2",
            Approach.BASEL_II_IRB: "basel2",

            Approach.BASEL_III_STANDARDIZED: "basel3",

            Approach.BASEL_III_IRB_FOUNDATION: "basel3",
            Approach.BASEL_III_IRB_ADVANCED: "basel3",
        }[self]

    @property
    def method(self) -> str:
        return {
            Approach.BASEL_II_STANDARDIZED: "standardized",
            Approach.BASEL_II_IRB: "irb",

            Approach.BASEL_III_STANDARDIZED: "standardized",

            Approach.BASEL_III_IRB_FOUNDATION: "irb",
            Approach.BASEL_III_IRB_ADVANCED: "irb",
        }[self]
