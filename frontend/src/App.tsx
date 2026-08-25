import { BrowserRouter, Route, Routes } from 'react-router-dom';
import { BrowseScreen } from './screens/BrowseScreen';
import { MovieDetailScreen } from './screens/MovieDetailScreen';

export default function App() {
  return (
    <BrowserRouter>
      <div className="app">
        <Routes>
          <Route path="/" element={<BrowseScreen />} />
          <Route path="/movie/:id" element={<MovieDetailScreen />} />
        </Routes>
      </div>
    </BrowserRouter>
  );
}
