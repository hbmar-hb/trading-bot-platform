"""Tests for symbol format normalization helpers."""

import pytest

from app.services.ai_scanner import to_ccxt
from app.engines.bot_activator import _to_compact_symbol, _symbol_matches


@pytest.mark.parametrize(
    "input_symbol, expected",
    [
        ("BTCUSDT", "BTC/USDT:USDT"),
        ("btcusdt", "BTC/USDT:USDT"),
        ("BTC/USDT", "BTC/USDT:USDT"),
        ("BTC/USDT:USDT", "BTC/USDT:USDT"),
        ("BTCUSDT.P", "BTC/USDT:USDT"),
        ("ETHUSDC", "ETH/USDC:USDC"),
        ("ETH/USDC:USDC", "ETH/USDC:USDC"),
        ("SOLBTC", "SOL/BTC:BTC"),
        ("1000PEPEUSDT", "1000PEPE/USDT:USDT"),
    ],
)
def test_to_ccxt_normalizes_to_perpetual_format(input_symbol, expected):
    assert to_ccxt(input_symbol) == expected


@pytest.mark.parametrize(
    "input_symbol, expected",
    [
        ("BTC/USDT:USDT", "BTCUSDT"),
        ("BTC/USDT", "BTCUSDT"),
        ("BTCUSDT", "BTCUSDT"),
        ("btcusdt", "BTCUSDT"),
        ("ETH/USDC:USDC", "ETHUSDC"),
    ],
)
def test_to_compact_symbol_normalizes_to_compact(input_symbol, expected):
    assert _to_compact_symbol(input_symbol) == expected


@pytest.mark.parametrize(
    "bot_symbol, signal_symbol, expected",
    [
        ("ARB/USDT:USDT", "ARB/USDT:USDT", True),
        ("ARBUSDT", "ARB/USDT:USDT", True),
        ("ARB/USDT", "ARB/USDT:USDT", True),
        ("BTC/USDT:USDT", "ETH/USDT:USDT", False),
        ("BTCUSDT", "ETH/USDT:USDT", False),
        ("", "ARB/USDT:USDT", False),
        ("ARB/USDT:USDT", "", False),
    ],
)
def test_symbol_matches_accepts_both_formats(bot_symbol, signal_symbol, expected):
    assert _symbol_matches(bot_symbol, signal_symbol) is expected
