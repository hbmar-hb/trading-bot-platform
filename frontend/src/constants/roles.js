export const ROLES = {
  ROL1: 'rol1',
  MODERATOR: 'moderator',
  ADMIN: 'admin',
  DEVELOPER: 'developer',
}

// Roles que tienen acceso a la aplicación en producción
export const AUTHORIZED_ROLES = [ROLES.ROL1, ROLES.MODERATOR, ROLES.ADMIN, ROLES.DEVELOPER]

// Roles que pueden acceder a funcionalidades de administrador/moderador
// (todo lo que NO debe ver rol1)
export const PRIVILEGED_ROLES = [ROLES.MODERATOR, ROLES.ADMIN, ROLES.DEVELOPER]

// Rutas permitidas explícitamente para rol1
export const ROL1_ROUTES = [
  '/dashboard',
  '/bots',
  '/bots/new',
  '/bots/:botId/edit',
  '/bots/:botId/activity',
  '/bots/:botId/optimizer',
  '/bots/:botId/effectiveness',
  '/positions',
  '/analytics',
  '/exchange-accounts',
  '/exchange-trades',
  '/manual-trading',
  '/docs',
]

// Helper para verificar si un usuario tiene alguno de los roles permitidos
export function hasAnyRole(user, roles) {
  return Boolean(user?.role && roles.includes(user.role))
}

// Helper específico: ¿el usuario es administrador (incluye developer por jerarquía)?
export function isAdmin(user) {
  return isAtLeastAdmin(user)
}

// Helpers jerárquicos
export function isAtLeastModerator(user) {
  return ['moderator', 'admin', 'developer'].includes(user?.role)
}

export function isAtLeastAdmin(user) {
  return ['admin', 'developer'].includes(user?.role)
}

export function isDeveloper(user) {
  return user?.role === 'developer'
}
