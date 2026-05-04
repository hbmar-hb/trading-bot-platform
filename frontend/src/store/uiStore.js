import { create } from 'zustand'

const savedTheme = localStorage.getItem('theme')
const initialDark = savedTheme !== 'light'   // dark por defecto

const applyTheme = (isDark) => {
  document.documentElement.classList.toggle('dark', isDark)
  localStorage.setItem('theme', isDark ? 'dark' : 'light')
}

// Aplicar inmediatamente al cargar
applyTheme(initialDark)

const useUiStore = create((set) => ({
  sidebarOpen: true,
  isDark: initialDark,
  notifications: [],

  toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen })),

  toggleTheme: () => set((s) => {
    applyTheme(!s.isDark)
    return { isDark: !s.isDark }
  }),

  addNotification: (notification) =>
    set((s) => ({
      notifications: [
        { id: Date.now(), ...notification },
        ...s.notifications.slice(0, 9),
      ]
    })),

  removeNotification: (id) =>
    set((s) => ({
      notifications: s.notifications.filter(n => n.id !== id)
    })),
}))

export default useUiStore
