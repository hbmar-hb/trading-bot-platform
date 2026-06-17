import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import ProtectedRoute from '@/components/Common/ProtectedRoute'
import AdminRoute from '@/components/Common/AdminRoute'
import Layout from '@/components/Common/Layout'

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
import AdminSystemPage from '@/pages/AdminSystemPage'
import MonteCarloPage from '@/pages/MonteCarloPage'
import PositionsPage       from '@/pages/PositionsPage'
import AnalyticsPage       from '@/pages/AnalyticsPage'
import ChartPage           from '@/pages/ChartPage'
import ExchangeAccountsPage from '@/pages/ExchangeAccountsPage'
import ExchangeTradesPage  from '@/pages/ExchangeTradesPage'
import ManualTradePage     from '@/pages/ManualTradePage'
import PaperTradingPage    from '@/pages/PaperTradingPage'
import SettingsPage        from '@/pages/SettingsPage'
import UsersPage           from '@/pages/UsersPage'
import AIPage              from '@/pages/AIPage'
import ChatPage            from '@/pages/ChatPage'

const guard = (Page) => (
  <ProtectedRoute>
    <Layout>
      <Page />
    </Layout>
  </ProtectedRoute>
)

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
        <Route path="/dashboard"                    element={guard(DashboardPage)} />
        <Route path="/bots"                         element={guard(BotsListPage)} />
        <Route path="/bots/new"                     element={guard(BotEditPage)} />
        <Route path="/bots/:botId/edit"             element={guard(BotEditPage)} />
        <Route path="/bots/:botId/activity"         element={guard(BotActivityPage)} />
        <Route path="/bots/:botId/optimizer"        element={guard(BotOptimizerPage)} />
        <Route path="/bots/:botId/effectiveness"   element={guard(EffectivenessDashboardPage)} />
        <Route path="/optimizer-db"                 element={guard(OptimizerDBPage)} />
        <Route path="/admin-system"                 element={guard(AdminSystemPage)} />
        <Route path="/monte-carlo"                  element={guard(MonteCarloPage)} />
        <Route path="/positions"                    element={guard(PositionsPage)} />
        <Route path="/analytics"                    element={guard(AnalyticsPage)} />
        <Route path="/chart"                        element={guard(ChartPage)} />
        <Route path="/exchange-accounts"            element={guard(ExchangeAccountsPage)} />
        <Route path="/exchange-trades"              element={guard(ExchangeTradesPage)} />
        <Route path="/manual-trading"               element={guard(ManualTradePage)} />
        <Route path="/paper-trading"                element={guard(PaperTradingPage)} />
        <Route path="/users"                        element={
          <ProtectedRoute><AdminRoute><Layout><UsersPage /></Layout></AdminRoute></ProtectedRoute>
        } />
        <Route path="/ai"                           element={guard(AIPage)} />
        <Route path="/chat"                         element={guard(ChatPage)} />
        <Route path="/settings"                     element={guard(SettingsPage)} />
        <Route path="*"                             element={<Navigate to="/dashboard" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
