import * as React from 'react';
import { Check, ChevronsUpDown, X } from 'lucide-react';
import { cn } from './utils';
import { Button } from './button';
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem } from './command';
import { Popover, PopoverContent, PopoverTrigger } from './popover';
import { Badge } from './badge';

interface MultiSelectProps {
  options: string[];
  selected: string[];
  onChange: (selected: string[]) => void;
  placeholder?: string;
  searchPlaceholder?: string;
  emptyText?: string;
  className?: string;
}

export function MultiSelect({
  options,
  selected,
  onChange,
  placeholder = '请选择...',
  searchPlaceholder = '搜索...',
  emptyText = '未找到结果',
  className,
}: MultiSelectProps) {
  const [open, setOpen] = React.useState(false);
  const [searchValue, setSearchValue] = React.useState('');

  const filteredOptions = options.filter((option) =>
    option.toLowerCase().includes(searchValue.toLowerCase())
  );

  const handleSelect = (option: string) => {
    const newSelected = selected.includes(option)
      ? selected.filter((item) => item !== option)
      : [...selected, option];
    onChange(newSelected);
  };

  const handleRemove = (option: string, e: React.MouseEvent) => {
    e.stopPropagation();
    onChange(selected.filter((item) => item !== option));
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          role="combobox"
          aria-expanded={open}
          className={cn('w-full justify-between h-auto min-h-[40px]', className)}
        >
          <div className="flex flex-wrap gap-1 flex-1">
            {selected.length === 0 ? (
              <span className="text-gray-500">{placeholder}</span>
            ) : (
              selected.slice(0, 3).map((item) => (
                <Badge key={item} variant="secondary" className="text-xs">
                  {item}
                  <button
                    className="ml-1 rounded-full outline-none hover:bg-gray-300"
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        handleRemove(item, e as any);
                      }
                    }}
                    onMouseDown={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                    }}
                    onClick={(e) => handleRemove(item, e)}
                  >
                    <X className="h-3 w-3" />
                  </button>
                </Badge>
              ))
            )}
            {selected.length > 3 && (
              <Badge variant="secondary" className="text-xs">
                +{selected.length - 3}
              </Badge>
            )}
          </div>
          <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-full p-0" align="start">
        <Command>
          <CommandInput
            placeholder={searchPlaceholder}
            value={searchValue}
            onValueChange={setSearchValue}
          />
          <CommandEmpty>{emptyText}</CommandEmpty>
          <CommandGroup className="max-h-64 overflow-auto">
            {filteredOptions.map((option) => (
              <CommandItem
                key={option}
                value={option}
                onSelect={() => handleSelect(option)}
                className="cursor-pointer"
              >
                <div
                  className={cn(
                    'mr-2 flex h-4 w-4 items-center justify-center rounded-sm border border-primary',
                    selected.includes(option)
                      ? 'bg-primary text-primary-foreground'
                      : 'opacity-50 [&_svg]:invisible'
                  )}
                >
                  <Check className="h-4 w-4" />
                </div>
                <span>{option}</span>
              </CommandItem>
            ))}
          </CommandGroup>
        </Command>
      </PopoverContent>
    </Popover>
  );
}