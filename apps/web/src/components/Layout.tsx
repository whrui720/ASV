import { Link, Outlet, useParams } from "react-router-dom";

export function Layout() {
  const { runId } = useParams();

  return (
    <div className="min-h-full flex flex-col">
      <header className="border-b bg-white sticky top-0 z-10">
        <div className="max-w-7xl mx-auto px-4 h-14 flex items-center gap-6">
          <Link to="/" className="font-semibold text-gray-900">
            ASV
          </Link>
          {runId && (
            <nav className="flex gap-4 text-sm text-gray-600">
              <Link to={`/runs/${runId}`} className="hover:text-gray-900">
                Overview
              </Link>
              <Link to={`/runs/${runId}/claims`} className="hover:text-gray-900">
                Claims
              </Link>
              <Link to={`/runs/${runId}/paper`} className="hover:text-gray-900">
                Paper
              </Link>
              <Link to={`/runs/${runId}/sources`} className="hover:text-gray-900">
                Sources
              </Link>
              <Link to={`/runs/${runId}/references`} className="hover:text-gray-900">
                References
              </Link>
              <Link to={`/runs/${runId}/console`} className="hover:text-gray-900">
                Console
              </Link>
            </nav>
          )}
          <div className="flex-1" />
          <nav className="flex gap-4 text-sm text-gray-600">
            <Link to="/compare" className="hover:text-gray-900">
              Compare
            </Link>
            <Link to="/benchmark" className="hover:text-gray-900">
              Benchmark
            </Link>
            <Link to="/config" className="hover:text-gray-900">
              Config
            </Link>
          </nav>
        </div>
      </header>
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 py-6">
        <Outlet />
      </main>
    </div>
  );
}
