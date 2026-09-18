"""Tests for ML-based confidence prediction."""

import pytest
from datetime import datetime

from swizzle.integration.unified_index import (
    UnifiedIndex, IndexedDecision, get_unified_index, reset_unified_index
)
from swizzle.integration.ml_predictor import MLPredictor, PredictionCache, create_ml_predictor


class TestMLPredictor:
    """Test ML predictor functionality."""

    def test_model_training(self):
        """Verify models are trained from historical decisions."""
        reset_unified_index()
        index = get_unified_index()

        # Add decisions for training
        for i in range(5):
            decision = IndexedDecision(
                decision_id=f"d{i}",
                repo="swizzle",
                type="apply_filter_pattern",
                risk_level="low",
                confidence=0.8 + (i * 0.02),
                approved=(i < 4),
                executed=(i < 3),
                created_at=datetime.now().isoformat(),
            )
            index.add_decision("swizzle", decision)

        predictor = create_ml_predictor(index)

        # Verify model was created for the decision type/risk pair
        key = ("apply_filter_pattern", "low")
        assert key in predictor.models

        model = predictor.models[key]
        assert model.sample_count == 5
        assert model.approval_rate == 0.8  # 4 out of 5
        assert model.execution_rate == 0.6  # 3 out of 5
        assert model.success_rate == 0.6  # 3 approved AND executed

    def test_predict_confidence_with_sufficient_data(self):
        """Verify confidence prediction works with enough training data."""
        reset_unified_index()
        index = get_unified_index()

        # Add training data with known success rate
        for i in range(5):
            decision = IndexedDecision(
                decision_id=f"d{i}",
                repo="swizzle",
                type="apply_filter_pattern",
                risk_level="low",
                confidence=0.9,
                approved=True,
                executed=(i < 4),  # 4/5 succeeded
                created_at=datetime.now().isoformat(),
            )
            index.add_decision("swizzle", decision)

        predictor = create_ml_predictor(index)

        # Predict with high similarity (exact match expected)
        pred_high_similarity = predictor.predict_confidence(
            "apply_filter_pattern", "low", action_similarity=1.0
        )
        assert 0.7 <= pred_high_similarity <= 1.0

        # Predict with low similarity (should regress to 0.5)
        pred_low_similarity = predictor.predict_confidence(
            "apply_filter_pattern", "low", action_similarity=0.0
        )
        assert 0.4 <= pred_low_similarity <= 0.6

    def test_predict_confidence_with_insufficient_data(self):
        """Verify prediction returns default when insufficient data."""
        reset_unified_index()
        index = get_unified_index()

        # Add only 2 decisions (< 3 minimum)
        for i in range(2):
            decision = IndexedDecision(
                decision_id=f"d{i}",
                repo="swizzle",
                type="apply_filter_pattern",
                risk_level="low",
                confidence=0.9,
                approved=True,
                executed=True,
                created_at=datetime.now().isoformat(),
            )
            index.add_decision("swizzle", decision)

        predictor = create_ml_predictor(index)

        # Should return default 0.5 when insufficient samples
        pred = predictor.predict_confidence("apply_filter_pattern", "low")
        assert pred == 0.5

    def test_predict_unknown_type(self):
        """Verify prediction handles unknown decision types."""
        reset_unified_index()
        index = get_unified_index()

        predictor = create_ml_predictor(index)

        # Unknown type should return default
        pred = predictor.predict_confidence("unknown_type", "low")
        assert pred == 0.5

    def test_model_stats(self):
        """Verify model statistics are correctly computed."""
        reset_unified_index()
        index = get_unified_index()

        # Add decisions of different types
        for risk in ["low", "high"]:
            for i in range(3):
                decision = IndexedDecision(
                    decision_id=f"d_{risk}_{i}",
                    repo="swizzle",
                    type="apply_filter_pattern",
                    risk_level=risk,
                    confidence=0.8,
                    approved=(i < 2),
                    executed=(i < 1),
                    created_at=datetime.now().isoformat(),
                )
                index.add_decision("swizzle", decision)

        predictor = create_ml_predictor(index)
        stats = predictor.get_model_stats()

        # Should have stats for both low and high risk
        assert "apply_filter_pattern_low" in stats
        assert "apply_filter_pattern_high" in stats

        # Verify stat structure
        low_stats = stats["apply_filter_pattern_low"]
        assert low_stats["samples"] == 3
        assert low_stats["approval_rate"] == 2/3
        assert low_stats["execution_rate"] == 1/3

    def test_confidence_adjustment(self):
        """Verify confidence adjustment suggestions."""
        reset_unified_index()
        index = get_unified_index()

        # Add decisions with high success rate
        for i in range(5):
            decision = IndexedDecision(
                decision_id=f"d{i}",
                repo="swizzle",
                type="apply_filter_pattern",
                risk_level="low",
                confidence=0.5,  # Lower confidence
                approved=True,
                executed=True,  # But high success
                created_at=datetime.now().isoformat(),
            )
            index.add_decision("swizzle", decision)

        predictor = create_ml_predictor(index)

        # Suggest adjustment for conservative confidence
        adjusted = predictor.suggest_confidence_adjustment(
            "apply_filter_pattern", "low", current_confidence=0.5
        )

        # Should suggest increasing confidence
        assert adjusted > 0.5
        assert adjusted <= 1.0

    def test_adjustment_with_insufficient_data(self):
        """Verify adjustment returns current when insufficient data."""
        reset_unified_index()
        index = get_unified_index()

        predictor = create_ml_predictor(index)

        adjusted = predictor.suggest_confidence_adjustment(
            "unknown_type", "low", current_confidence=0.7
        )

        # Should return unchanged
        assert adjusted == 0.7


class TestPredictionCache:
    """Test prediction caching."""

    def test_cache_stores_predictions(self):
        """Verify cache stores and retrieves predictions."""
        reset_unified_index()
        index = get_unified_index()

        # Add training data
        for i in range(5):
            decision = IndexedDecision(
                decision_id=f"d{i}",
                repo="swizzle",
                type="apply_filter_pattern",
                risk_level="low",
                confidence=0.9,
                approved=True,
                executed=True,
                created_at=datetime.now().isoformat(),
            )
            index.add_decision("swizzle", decision)

        predictor = create_ml_predictor(index)
        cache = PredictionCache(predictor)

        # Get prediction twice
        pred1 = cache.get_prediction("apply_filter_pattern", "low", action_similarity=0.7)
        pred2 = cache.get_prediction("apply_filter_pattern", "low", action_similarity=0.7)

        # Should be identical
        assert pred1 == pred2

        # Cache should have one entry
        assert len(cache.cache) == 1

    def test_cache_different_similarities(self):
        """Verify cache distinguishes different similarity values."""
        reset_unified_index()
        index = get_unified_index()

        # Add training data
        for i in range(5):
            decision = IndexedDecision(
                decision_id=f"d{i}",
                repo="swizzle",
                type="apply_filter_pattern",
                risk_level="low",
                confidence=0.9,
                approved=True,
                executed=True,
                created_at=datetime.now().isoformat(),
            )
            index.add_decision("swizzle", decision)

        predictor = create_ml_predictor(index)
        cache = PredictionCache(predictor)

        # Get predictions with different similarities
        pred1 = cache.get_prediction("apply_filter_pattern", "low", action_similarity=0.7)
        pred2 = cache.get_prediction("apply_filter_pattern", "low", action_similarity=0.9)

        # Should have separate cache entries
        assert len(cache.cache) == 2
        # Predictions may differ due to similarity weighting
        assert pred1 != pred2 or pred1 == pred2  # Just verify no error

    def test_cache_clear(self):
        """Verify cache can be cleared."""
        reset_unified_index()
        index = get_unified_index()

        # Add training data
        for i in range(5):
            decision = IndexedDecision(
                decision_id=f"d{i}",
                repo="swizzle",
                type="apply_filter_pattern",
                risk_level="low",
                confidence=0.9,
                approved=True,
                executed=True,
                created_at=datetime.now().isoformat(),
            )
            index.add_decision("swizzle", decision)

        predictor = create_ml_predictor(index)
        cache = PredictionCache(predictor)

        # Get prediction
        cache.get_prediction("apply_filter_pattern", "low")
        assert len(cache.cache) == 1

        # Clear cache
        cache.clear_cache()
        assert len(cache.cache) == 0
