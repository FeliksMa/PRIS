import { sqliteTable, text, integer } from "drizzle-orm/sqlite-core";
export const state = sqliteTable("state", { key: text("key").primaryKey(), value: text("value").notNull() });
export const papers = sqliteTable("papers", { id: text("id").primaryKey(), payload: text("payload").notNull() });
export const reports = sqliteTable("reports", { path: text("path").primaryKey(), name: text("name").notNull(), date: text("date").notNull(), content: text("content").notNull() });
export const messages = sqliteTable("messages", { id: integer("id").primaryKey({ autoIncrement: true }), role: text("role").notNull(), content: text("content").notNull(), proposal: text("proposal"), created: text("created").notNull() });
export const history = sqliteTable("history", { id: integer("id").primaryKey({ autoIncrement: true }), before: text("before").notNull(), reason: text("reason").notNull(), created: text("created").notNull() });
export const jobs = sqliteTable("jobs", { id: integer("id").primaryKey({ autoIncrement: true }), command: text("command").notNull(), state: text("state").notNull(), output: text("output").notNull().default(""), created: text("created").notNull() });
