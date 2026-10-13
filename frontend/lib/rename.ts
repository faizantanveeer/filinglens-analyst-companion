/**
 * The app used to be called FilingLens and kept its browser state under "filinglens.*" keys.
 * Before any other script runs, move those to "fincite.*" so visitors stay signed in and keep
 * their settings and the keys in their current tab. Existing "fincite.*" values always win.
 */
export const RENAME_SCRIPT = `(function(){try{[localStorage,sessionStorage].forEach(function(s){for(var i=s.length-1;i>=0;i--){var k=s.key(i);if(k&&k.indexOf("filinglens.")===0){var n="fincite."+k.slice(11);if(s.getItem(n)===null)s.setItem(n,s.getItem(k));s.removeItem(k)}}})}catch(e){}})()`;
