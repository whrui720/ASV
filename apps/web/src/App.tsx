import { Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { RunsIndex } from "./routes/RunsIndex";
import { RunOverview } from "./routes/RunOverview";
import { ClaimsExplorer } from "./routes/ClaimsExplorer";
import { ClaimDetailDrawer } from "./components/ClaimDetailDrawer";
import { PaperView } from "./routes/PaperView";
import { SourcesView } from "./routes/SourcesView";
import { LiveConsole } from "./routes/LiveConsole";
import { ComparePage } from "./routes/ComparePage";
import { ConfigPage } from "./routes/ConfigPage";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<RunsIndex />} />
        <Route path="compare" element={<ComparePage />} />
        <Route path="config" element={<ConfigPage />} />
        <Route path="runs/:runId" element={<RunOverview />} />
        <Route path="runs/:runId/claims" element={<ClaimsExplorer />}>
          <Route path=":claimId" element={<ClaimDetailDrawer />} />
        </Route>
        {/* The same drawer nests under both parents so a highlight click opens
            it in place, without kicking the reader out of the PDF. */}
        <Route path="runs/:runId/paper" element={<PaperView />}>
          <Route path=":claimId" element={<ClaimDetailDrawer />} />
        </Route>
        <Route path="runs/:runId/sources" element={<SourcesView />} />
        <Route path="runs/:runId/console" element={<LiveConsole />} />
      </Route>
    </Routes>
  );
}
