// Reference ratings are used for browser-local scoring and are not displayed by the UI.
// This encoding is a storage format, not encryption or a secrecy guarantee.
const packed = "ODI2MzEzMTc1ODg1ODUzNDU4NDg3ODcyMzYzNjY3MjY1ODU1NDMxMjQyNTYyODM3MjgzNzM4ODI4ODI2ODY4NzQ0ODc0NjE4NDExODQ3NjE4NjU0NzU0";
export const referenceLevels = () => Array.from(atob(packed), Number);
