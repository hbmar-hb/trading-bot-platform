import { useState, useEffect, useCallback } from 'react'

const STORAGE_KEY = 'trading_bot_indicator_configs'

const DEFAULT_ICT_CONFIG = {
  version: '1.0',
  signals: true,
  showSwingAreas: false,
  tradingOverlay: false,
  tradingDashboard: 'top_right',
  proFilters: {
    enabled: true,
    trendFilter: true,
    requireSweep: true,
    momentumFilter: true,
    cooldown: true,
    cooldownBars: 5,
    pivotLen: 5,
    atrMult: 0.5,
    trendLen: 50,
  },
  colors: {
    signalLong: '#22c55e',
    signalShort: '#ef4444',
    signalContra: '#fbbf24',
    dashboardBg: 'rgba(0,0,0,0.7)',
    overlayBull: '#26c6da',
    overlayBear: '#ef5350',
  },
  visibility: {
    bosChoch: true,
    orderBlocks: true,
    fairValueGaps: true,
    pivots: false,
    entries: true,
    levels: true,
  },
}

function loadFromStorage() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) return JSON.parse(raw)
  } catch { }
  return { ict: DEFAULT_ICT_CONFIG }
}

function saveToStorage(configs) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(configs))
  } catch { }
}

export function useIndicatorConfig() {
  const [configs, setConfigs] = useState(() => loadFromStorage())

  useEffect(() => {
    saveToStorage(configs)
  }, [configs])

  const getConfig = useCallback((key) => {
    return configs[key] ?? DEFAULT_ICT_CONFIG
  }, [configs])

  const setConfig = useCallback((key, next) => {
    setConfigs(prev => ({
      ...prev,
      [key]: typeof next === 'function' ? next(prev[key] ?? DEFAULT_ICT_CONFIG) : next,
    }))
  }, [])

  const resetConfig = useCallback((key) => {
    setConfigs(prev => ({
      ...prev,
      [key]: DEFAULT_ICT_CONFIG,
    }))
  }, [])

  return { getConfig, setConfig, resetConfig, DEFAULT_ICT_CONFIG }
}
