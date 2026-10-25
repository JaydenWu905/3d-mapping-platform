import { createContext } from 'react';

export type TaskTitle = { path: string; title: string };
export const TaskTitleContext = createContext<(value: TaskTitle) => void>(() => {});
