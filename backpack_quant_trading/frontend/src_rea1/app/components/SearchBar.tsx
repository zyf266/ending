import React from 'react';
import { Search, Filter } from 'lucide-react';

export function SearchBar() {
  return (
    <div className="flex items-center gap-3 flex-1">
      <div className="relative flex-1 max-w-md">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400" />
        <input
          type="text"
          placeholder="搜索策略名称或代码..."
          className="w-full pl-10 pr-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
        />
      </div>
      
      <button className="flex items-center gap-2 px-4 py-2 border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors">
        <Filter className="w-4 h-4" />
        <span className="text-sm text-gray-700">全部状态</span>
        <svg className="w-4 h-4 text-gray-500" viewBox="0 0 20 20" fill="currentColor">
          <path fillRule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clipRule="evenodd" />
        </svg>
      </button>
    </div>
  );
}
