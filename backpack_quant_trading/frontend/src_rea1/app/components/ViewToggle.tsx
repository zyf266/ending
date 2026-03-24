import React from 'react';
import { Grid3x3, List, Plus } from 'lucide-react';

interface ViewToggleProps {
  viewMode: 'grid' | 'list';
  setViewMode: (mode: 'grid' | 'list') => void;
}

export function ViewToggle({ viewMode, setViewMode }: ViewToggleProps) {
  const tabs = [
    { id: 1, label: '风格一', active: true },
    { id: 2, label: '风格二', active: false },
    { id: 3, label: '风格三', active: false, color: 'yellow' },
    { id: 4, label: '风格四', active: false }
  ];

  return (
    <div className="flex items-center gap-2">
      {/* Style Tabs */}
      {tabs.map((tab) => (
        <button
          key={tab.id}
          className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
            tab.active
              ? 'bg-blue-600 text-white'
              : tab.color === 'yellow'
              ? 'bg-yellow-100 text-yellow-700 hover:bg-yellow-200'
              : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
          }`}
        >
          {tab.active && (
            <span className="inline-block mr-1">
              <svg className="w-4 h-4 inline" viewBox="0 0 16 16" fill="currentColor">
                <path d="M8 2a1 1 0 0 1 1 1v4h4a1 1 0 1 1 0 2H9v4a1 1 0 1 1-2 0V9H3a1 1 0 0 1 0-2h4V3a1 1 0 0 1 1-1z"/>
              </svg>
            </span>
          )}
          {tab.label}
        </button>
      ))}

      {/* View Mode Toggle */}
      <div className="flex gap-1 bg-gray-100 p-1 rounded-lg ml-2">
        <button
          onClick={() => setViewMode('grid')}
          className={`p-2 rounded-md transition-colors ${
            viewMode === 'grid'
              ? 'bg-blue-600 text-white'
              : 'text-gray-600 hover:bg-gray-200'
          }`}
        >
          <Grid3x3 className="w-4 h-4" />
        </button>
        <button
          onClick={() => setViewMode('list')}
          className={`p-2 rounded-md transition-colors ${
            viewMode === 'list'
              ? 'bg-blue-600 text-white'
              : 'text-gray-600 hover:bg-gray-200'
          }`}
        >
          <List className="w-4 h-4" />
        </button>
      </div>

      {/* Add Button */}
      <button className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors">
        <Plus className="w-4 h-4" />
        <span className="text-sm font-medium">新建策略</span>
      </button>
    </div>
  );
}
