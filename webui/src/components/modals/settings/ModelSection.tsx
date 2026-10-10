import React, { useMemo, useCallback } from 'react';
import { Cpu } from 'lucide-react';
import type { ModelOption } from '../../../bridge';
import { sortModelsByVersion, DEFAULT_MODEL } from '../../../utils';
import { CustomSelect } from './CustomSelect';

interface ModelSectionProps {
  preferredModel: string;
  setPreferredModel: (model: string) => void;
  availableModels: ModelOption[];
}

export const ModelSection: React.FC<ModelSectionProps> = React.memo(({
  preferredModel,
  setPreferredModel,
  availableModels,
}) => {
  const sortedModels = useMemo(
    () => sortModelsByVersion(availableModels),
    [availableModels]
  );

  const handlePrimaryModelChange = useCallback((nextPrimary: string) => {
    setPreferredModel(nextPrimary);
  }, [setPreferredModel]);

  const primaryModelOptions = useMemo(
    () => sortedModels.map(m => ({
      value: m.id,
      label: m.label,
      badge: (m.is_default || m.id === DEFAULT_MODEL || m.id === 'gemini-2.5-flash') ? 'Default' : undefined,
    })),
    [sortedModels],
  );

  return (
    <div className="space-y-3">
      <div className="space-y-1 min-w-0">
        <div className="flex items-center gap-2">
          <Cpu className="w-4 h-4 text-[var(--accent-text)] shrink-0" />
          <h3 className="text-xs font-bold uppercase tracking-wider text-[var(--text-secondary)]">
            Modello di trascrizione
          </h3>
        </div>
      </div>

      <CustomSelect
        value={preferredModel}
        onChange={handlePrimaryModelChange}
        options={primaryModelOptions}
      />
    </div>
  );
});

ModelSection.displayName = 'ModelSection';
