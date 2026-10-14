CREATE TABLE `history` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`before` text NOT NULL,
	`reason` text NOT NULL,
	`created` text NOT NULL
);
--> statement-breakpoint
CREATE TABLE `jobs` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`command` text NOT NULL,
	`state` text NOT NULL,
	`output` text DEFAULT '' NOT NULL,
	`created` text NOT NULL
);
--> statement-breakpoint
CREATE TABLE `messages` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`role` text NOT NULL,
	`content` text NOT NULL,
	`proposal` text,
	`created` text NOT NULL
);
--> statement-breakpoint
CREATE TABLE `papers` (
	`id` text PRIMARY KEY NOT NULL,
	`payload` text NOT NULL
);
--> statement-breakpoint
CREATE TABLE `reports` (
	`path` text PRIMARY KEY NOT NULL,
	`name` text NOT NULL,
	`date` text NOT NULL,
	`content` text NOT NULL
);
--> statement-breakpoint
CREATE TABLE `state` (
	`key` text PRIMARY KEY NOT NULL,
	`value` text NOT NULL
);
