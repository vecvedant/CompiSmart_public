import { BrowserRouter, Route, Routes } from "react-router-dom";
import NicheSelector from "./pages/NicheSelector";
import FeedView from "./pages/FeedView";
import CompareView from "./pages/CompareView";
import DraftsView from "./pages/DraftsView";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<NicheSelector />} />
        <Route path="/feed/:niche" element={<FeedView />} />
        <Route path="/feed/:niche/drafts" element={<DraftsView />} />
        <Route path="/drafts" element={<DraftsView />} />
        <Route path="/compare/:assetA/:assetB" element={<CompareView />} />
      </Routes>
    </BrowserRouter>
  );
}
