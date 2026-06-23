import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import ProtectedRoute from '@/components/Common/ProtectedRoute'
import RoleRoute from '@/components/Common/RoleRoute'
import Layout from '@/components/Common/Layout'
import { AUTHORIZED_ROLES, ROLES } from '@/constants/roles'

import LoginPage                from '@/pages/LoginPage'
import ChangePasswordForcedPage from '@/pages/ChangePasswordForcedPage'
import ForgotPasswordPage  from '@/pages/ForgotPasswordPage'
import ResetPasswordPage   from '@/pages/ResetPasswordPage'
import VerifyEmailPage     from '@/pages/VerifyEmailPage'
import DashboardPage       from '@/pages/DashboardPage'
import BotsListPage        from '@/pages/BotsListPage'
import BotEditPage         from '@/pages/BotEditPage'
import BotActivityPage     from '@/pages/BotActivityPage'
import BotOptimizerPage   from '@/pages/BotOptimizerPage'
import EffectivenessDashboardPage from '@/pages/EffectivenessDashboardPage'
import OptimizerDBPage from '@/pages/OptimizerDBPage'
import PositionsPage       from '@/pages/PositionsPage'
import AnalyticsPage       from '@/pages/AnalyticsPage'
import ChartPage           from '@/pages/ChartPage'
import ExchangeAccountsPage from '@/pages/ExchangeAccountsPage'
import ExchangeTradesPage  from '@/pages/ExchangeTradesPage'
import ManualTradePage     from '@/pages/ManualTradePage'
import PaperTradingPage    from '@/pages/PaperTradingPage'
import SettingsPage        from '@/pages/SettingsPage'
import UsersPage           from '@/pages/UsersPage'
import AdminSystemPage     from '@/pages/AdminSystemPage'
import AIPage              from '@/pages/AIPage'
import MonteCarloPage      from '@/pages/MonteCarloPage'
import ChatPage            from '@/pages/ChatPage'
import DocumentationPage   from '@/pages/DocumentationPage'

const guard = (Page, allowedRoles = AUTHORIZED_ROLES) => (
  <ProtectedRoute>
    <RoleRoute allowedRoles={allowedRoles}>
      <Layout>
        <Page />
      </Layout>
    </RoleRoute>
  </ProtectedRoute>
)

const guardDeveloper = (Page) => guard(Page, [ROLES.DEVELOPER])

export default function AppRoutes() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login"                        element={<LoginPage />} />
        <Route path="/forgot-password"              element={<ForgotPasswordPage />} />
        <Route path="/reset-password"               element={<ResetPasswordPage />} />
        <Route path="/verify-email"                 element={<VerifyEmailPage />} />
        <Route path="/change-password"              element={
          <ProtectedRoute><ChangePasswordForcedPage /></ProtectedRoute>
        } />
        <Route path="/"                             element={<Navigate to="/dashboard" replace />} />

        {/* Rol1 + moderator + admin */}
        <Route path="/dashboard"                    element={guard(DashboardPage)} />
        <Route path="/bots"                         element={guard(BotsListPage)} />
        <Route path="/bots/new"                     element={guard(BotEditPage)} />
        <Route path="/bots/:botId/edit"             element={guard(BotEditPage)} />
        <Route path="/bots/:botId/activity"         element={guard(BotActivityPage)} />
        <Route path="/bots/:botId/optimizer"        element={guardDeveloper(BotOptimizerPage)} />
        <Route path="/bots/:botId/effectiveness"   element={guard(EffectivenessDashboardPage)} />
        <Route path="/positions"                    element={guard(PositionsPage)} />
        <Route path="/analytics"                    element={guard(AnalyticsPage)} />
        <Route path="/exchange-accounts"            element={guard(ExchangeAccountsPage)} />
        <Route path="/exchange-trades"              element={guard(ExchangeTradesPage)} />
        <Route path="/manual-trading"               element={guard(ManualTradePage)} />
        <Route path="/settings"                     element={guard(SettingsPage)} />
        <Route path="/docs"                         element={guard(DocumentationPage)} />

        {/* Developer únicamente */}
        <Route path="/chart"                        element={guardDeveloper(ChartPage)} />
        <Route path="/ai"                           element={guardDeveloper(AIPage)} />
        <Route path="/montecarlo"                   element={guardDeveloper(MonteCarloPage)} />
        <Route path="/paper-trading"                element={guardDeveloper(PaperTradingPage)} />
        <Route path="/optimizer-db"                 element={guardDeveloper(OptimizerDBPage)} />
        <Route path="/chat"                         element={guardDeveloper(ChatPage)} />

        {/* Developer únicamente */}
        <Route path="/users"                        element={
          <ProtectedRoute><RoleRoute allowedRoles={[ROLES.DEVELOPER]}><Layout><UsersPage /></Layout></RoleRoute></ProtectedRoute>
        } />
        {/* Developer únicamente */}
        <Route path="/admin/system"                  element={
          <ProtectedRoute><RoleRoute allowedRoles={[ROLES.DEVELOPER]}><Layout><AdminSystemPage /></Layout></RoleRoute></ProtectedRoute>
        } />

        <Route path="*"                             element={<Navigate to="/dashboard" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
