import { Routes, Route, Navigate } from "react-router-dom";
import AppLayout from "./layouts/AppLayout";
import Dashboard from "./pages/Dashboard";
import ProjectList from "./pages/ProjectList";
import ProjectDetail from "./pages/ProjectDetail";
import SessionDetail from "./pages/SessionDetail";
import ConversationView from "./pages/ConversationView";
import ImuPage from "./pages/ImuPage";
import ResourceBrowser from "./pages/ResourceBrowser";
import ScheduledTasks from "./pages/ScheduledTasks";
import Settings from "./pages/Settings";
import NotFound from "./pages/NotFound";
import { useGlobalWS } from "./hooks/useGlobalWS";

export default function App() {
  useGlobalWS();

  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={<Navigate to="/imu" replace />} />
        <Route path="dashboard" element={<Dashboard />} />
        <Route path="projects" element={<ProjectList />} />
        <Route path="projects/:projectId" element={<ProjectDetail />} />
        <Route
          path="projects/:projectId/sessions/:runId"
          element={<SessionDetail />}
        />
        <Route
          path="projects/:projectId/conversations/:conversationId"
          element={<ConversationView />}
        />
        <Route path="imu" element={<ImuPage />} />
        <Route path="imu/:conversationId" element={<ImuPage />} />
        <Route path="schedules" element={<Navigate to="/schedules/recurring" replace />} />
        <Route path="schedules/recurring" element={<ScheduledTasks />} />
        <Route path="schedules/one-time" element={<ScheduledTasks />} />
        <Route path="schedules/runs" element={<ScheduledTasks />} />
        <Route
          path="resources/:resourceType"
          element={<ResourceBrowser />}
        />
        <Route path="settings" element={<Settings />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
