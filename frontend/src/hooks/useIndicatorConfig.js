import { useState, useEffect, useCallback } from 'react'
import { indicators } from '@/indicators/registry'

const STORAGE_KEY = 'trading_bot_indicator_configs'

// Construir defaults dinámicamente desde los indicadores registrados
function buildDefaults() {
  const defaults = {}
  for (const ind of indicators) {
    defaults[ind.id] = ind.defaultConfig
  }
  return defaults
}

function loadFromStorage() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) {
      const parsed = JSON.parse(raw)
      // Merge con defaults por si hay indicadores nuevos
      const defaults = buildDefaults()
      return { ...defaults, ...parsed }
    }
  } catch { }
  return buildDefaults()
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
    const defaults = buildDefaults()
    return configs[key] ?? defaults[key]
  }, [configs])

  const setConfig = useCallback((key, next) => {
    setConfigs(prev => {
      const defaults = buildDefaults()
      const base = prev[key] ?? defaults[key]
      return {
        ...prev,
        [key]: typeof next === 'function' ? next(base) : next,
      }
    })
  }, [])

  const resetConfig = useCallback((key) => {
    setConfigs(prev => {
      const defaults = buildDefaults()
      return { ...prev, [key]: defaults[key] }
    })
  }, [])

  return { configs, getConfig, setConfig, resetConfig }
}
