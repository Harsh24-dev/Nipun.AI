import { Component } from 'react'
import { Toaster } from "@/components/ui/toaster"
import { QueryClientProvider } from '@tanstack/react-query'
import { queryClientInstance } from '@/lib/query-client'
import { BrowserRouter as Router, Route, Routes, Navigate, useLocation } from 'react-router-dom';
import ScrollToTop from './components/ScrollToTop';
import { AppProvider, useApp } from '@/lib/AppContext';
import ThemeStyles from '@/lib/theme/ThemeStyles';

import Landing from '@/pages/Landing';
import NipunLogin from '@/pages/NipunLogin';
import NipunSignup from '@/pages/NipunSignup';
import NipunResetPassword from '@/pages/NipunResetPassword';
import Onboarding from '@/pages/Onboarding';
import Home from '@/pages/Home';
import Workspace from '@/pages/Workspace';
import NipunSettings from '@/pages/NipunSettings';
import AdminDashboard from '@/pages/AdminDashboard';
import AdminUsers from '@/pages/AdminUsers';
import AdminMonitoring from '@/pages/AdminMonitoring';
import TaskRunnerHost from '@/components/task/TaskRunnerHost';

// A single throwing card render (or any child) must not white-screen the whole app.
// This boundary catches render/lifecycle errors below it and shows a recoverable fallback.
class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, info) {
    console.error("ErrorBoundary caught an error:", error, info);
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-screen flex items-center justify-center p-6" style={{ background: "var(--background)" }}>
          <div className="max-w-md w-full flex items-start gap-3 p-4 rounded-lg" style={{ background: "rgba(220,38,38,0.06)" }}>
            <div>
              <p className="text-sm font-medium" style={{ color: "var(--text)" }}>Something went wrong.</p>
              <p className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>
                {this.state.error?.message || "An unexpected error occurred while rendering this view."}
              </p>
              <div className="flex gap-2 mt-3">
                <button onClick={this.handleReset}
                  className="px-3 py-1.5 rounded-md text-xs font-medium"
                  style={{ background: "var(--accent)", color: "var(--accent-text)" }}>
                  Try again
                </button>
                <button onClick={() => window.location.reload()}
                  className="px-3 py-1.5 rounded-md text-xs font-medium border"
                  style={{ borderColor: "var(--border)", color: "var(--text-muted)" }}>
                  Reload
                </button>
              </div>
            </div>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

function NipunProtectedRoute({ children, adminOnly = false }) {
  const { isAuthenticated, user, hasOnboarded, profileHydrated } = useApp();
  const location = useLocation();

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  // Wait for the server profile before deciding on onboarding — otherwise a returning user on a
  // fresh device briefly gets redirected to onboarding before their profile loads.
  if (!profileHydrated) {
    return (
      <div className="min-h-screen flex items-center justify-center" style={{ background: "var(--background)" }}>
        <div className="h-8 w-8 rounded-full border-2 border-t-transparent animate-spin" style={{ borderColor: "var(--accent)", borderTopColor: "transparent" }} />
      </div>
    );
  }

  if (!hasOnboarded && location.pathname !== "/onboarding") {
    return <Navigate to="/onboarding" replace />;
  }

  if (adminOnly && user?.role !== "admin") {
    return <Navigate to="/home" replace />;
  }

  return children;
}

function PublicOnlyRoute({ children }) {
  const { isAuthenticated, hasOnboarded } = useApp();
  if (isAuthenticated && hasOnboarded) {
    return <Navigate to="/home" replace />;
  }
  return children;
}

const AuthenticatedApp = () => {
  return (
    <Routes>
      {/* Public */}
      <Route path="/" element={<Landing />} />
      <Route path="/login" element={<PublicOnlyRoute><NipunLogin /></PublicOnlyRoute>} />
      <Route path="/signup" element={<PublicOnlyRoute><NipunSignup /></PublicOnlyRoute>} />
      <Route path="/reset-password" element={<NipunResetPassword />} />

      {/* Authenticated */}
      <Route path="/onboarding" element={<NipunProtectedRoute><Onboarding /></NipunProtectedRoute>} />
      <Route path="/home" element={<NipunProtectedRoute><Home /></NipunProtectedRoute>} />
      <Route path="/workspace" element={<NipunProtectedRoute><Workspace /></NipunProtectedRoute>} />
      <Route path="/workspace/:sessionId" element={<NipunProtectedRoute><Workspace /></NipunProtectedRoute>} />
      <Route path="/settings" element={<NipunProtectedRoute><NipunSettings /></NipunProtectedRoute>} />

      {/* Admin */}
      <Route path="/admin" element={<NipunProtectedRoute adminOnly><AdminDashboard /></NipunProtectedRoute>} />
      <Route path="/admin/users" element={<NipunProtectedRoute adminOnly><AdminUsers /></NipunProtectedRoute>} />
      <Route path="/admin/monitoring" element={<NipunProtectedRoute adminOnly><AdminMonitoring /></NipunProtectedRoute>} />

      {/* Catch all */}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
};

function App() {
  return (
    <QueryClientProvider client={queryClientInstance}>
      <AppProvider>
        <Router>
          <ThemeStyles />
          <ScrollToTop />
          <ErrorBoundary>
            <AuthenticatedApp />
            <TaskRunnerHost />
          </ErrorBoundary>
        </Router>
        <Toaster />
      </AppProvider>
    </QueryClientProvider>
  )
}

export default App