export interface DocumentState {
  full_name: string | null;
  home_address: string | null;
  covers_worldwide_assets: boolean | null;
  has_children: boolean | null;
  children?: string[] | null;
  children_names?: string[] | null;
  executor: {
    name: string | null;
    relationship: string | null;
  };
  specific_gifts: string[] | null;
  additional_wishes: string | string[] | null;
  _meta?: {
    llm_calls?: number;
    session_id?: string;
    [key: string]: any;
  };
}

export interface ChatMessage {
  id: string;
  role: 'assistant' | 'user';
  content: string;
  subContent?: string;
  timestamp: string;
  options?: ChoiceOption[];
}

export interface ChoiceOption {
  label: string;
  field: string;
  value: boolean | string[] | string;
}

export interface StepItem {
  id: string;
  label: string;
  icon: string;
  value: string | null;
  isConfirmed: boolean;
}
